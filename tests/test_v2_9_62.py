"""2.9.62: Trial Balance / Statement of Account - tick several branches, departments and projects."""
import tempfile
import unittest
from types import SimpleNamespace

import ledger_reports
from test_final_features import new_db

BASE = {"profit_loss_only": True, "first_column": "USD", "second_column": "none"}


def balances(report):
    return {r[0]: float(r[-1]) for r in report["sections"][0]["rows"] if r and str(r[0]).isdigit()}


class SeveralFiltersTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.db, user = new_db(self.folder.name)
        db = self.db
        self.d1 = db.save_department({"name": "Sales"}, user); self.d2 = db.save_department({"name": "Site Works"}, user); self.d3 = db.save_department({"name": "Office"}, user)
        self.north = db.save_branch({"name": "North"}, user); self.south = db.save_branch({"name": "South"}, user)
        for day, amount, department, branch in (("10-02-2025", "300", "D01", "North"), ("11-02-2025", "50", "D02", "South"), ("12-02-2025", "7", "D03", "Head Office")):
            db.save_journal_voucher({"entry_date": day, "description": "Cost", "currency": "USD", "branch": branch}, [
                {"account_code": "601100000", "side": "D", "amount": amount, "department": department}, {"account_code": "531", "side": "C", "amount": amount}], user)
        self.account = "601100000"

    def tearDown(self): self.folder.cleanup()

    def total(self, **options):
        return balances(ledger_reports.build_account_report(self.db, {**BASE, **options})).get(self.account, 0.0)

    def test_departments(self):
        self.assertEqual(self.total(), 357)
        self.assertEqual(self.total(department_ids=[self.d1["id"], self.d2["id"]]), 350)
        self.assertEqual(self.total(department_ids=[self.d3["id"]]), 7)
        self.assertEqual(self.total(department_id=self.d2["id"]), 50)  # one value, as before

    def test_branches(self):
        self.assertEqual(self.total(branch_ids=[self.north["id"], self.south["id"]]), 350)
        self.assertEqual(self.total(branch_ids=[self.south["id"]]), 50)

    def test_filter_text_in_header(self):
        report = ledger_reports.build_account_report(self.db, {**BASE, "branch_ids": [self.north["id"]], "filter_text": "Branch: North"})
        self.assertIn("Filters: Branch: North", report["meta"][-1])


class DesktopOptionsTest(unittest.TestCase):
    def test_ticked_values_are_sent_as_lists(self):
        import desktop_balance_reports as reports
        from desktop_dimensions import DimensionsMixin
        var = lambda value: SimpleNamespace(get=lambda: value)
        v = {"account_from": var(""), "account_to": var(""), "date_from": var("01-01-2025"), "date_to": var("31-12-2025"), "print_date": var(""),
             "first_column": var("account"), "second_column": var("none"), "summary_digits": var("4"), "posting": var("Posted only"),
             "department": var("D01 - Sales; D03 - Office"), "project": var("All"), "branch": var("North; South")}
        app = SimpleNamespace(dimension_code=DimensionsMixin.dimension_code,
                              client=SimpleNamespace(branches=lambda: [{"id": 4, "name": "North"}, {"id": 5, "name": "South"}]))
        options = reports.BalanceReportsMixin.balance_options(app, {"vars": v, "flags": {"include_zero": var(False)}, "currencies": {}, "statement": False})
        self.assertEqual((options["departments"], options["projects"], options["branch_ids"]), (["D01", "D03"], [], [4, 5]))
        self.assertEqual(options["filter_text"], "Branch: North, South   Department: D01, D03")


if __name__ == "__main__":
    unittest.main()
