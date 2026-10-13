"""2.9.50: 'Calcul du taux récupérable' worksheet, checked against the bureau's Q2 2018 example."""
import unittest
from decimal import Decimal

import vat_return


def doc(category, base, vat=0, treatment="standard", use="mixed", exempt=0, recoverable=True):
    return {"category": category, "base": base, "exempt": exempt, "vat": vat, "treatment": treatment, "use": use, "recoverable": recoverable,
            "currency": "LBP", "lbp_rate": 1, "date": "2018-05-01"}


class RecoverableRateSheetTest(unittest.TestCase):
    def setUp(self):
        sales = [doc("sales", 1102016774.26, 121222000), doc("sales", 207439582.73, treatment="zero_rated"),
                 doc("sales", 5052823.42, treatment="exempt"), doc("sales", 4522500.0, treatment="exempt")]
        taxable, export, exempt = 1102016774.26, 207439582.73, 5052823.42 + 4522500.0
        self.ratio = Decimal(str(round((taxable + export) / (taxable + export + exempt), 6)))
        purchases = [doc("assets", 15263711.64, 1679008.28), doc("purchases", 1043587670.27, 114794643.73, use="taxable"),
                     doc("expenses", 124304409.55, 13673485.05)]
        self.result = {"currency_filter": "All", "include_review": False, "deduction_ratio": float(self.ratio), "ratio_source": "year-to-date turnover",
                       "totals_lbp": {"total_output": 122468113.05, "adj_input": 0, "annual_adjustment": 0},
                       "documents": sales + purchases, "year": 2018, "quarter": 2, "date_from": "2018-04-01", "date_to": "2018-06-30",
                       "credit_brought_forward_lbp": 0, "payable_lbp": 0, "credit_carried_forward_lbp": 7567575}

    def test_matches_the_worksheet(self):
        meta, sections = vat_return.recoverable_rate_sheet(self.result, {"company_name": "ABIAD GROUP S.A.L"})
        self.assertIn("ABIAD GROUP", meta[0])
        produits = {row[0]: row[2] for row in sections[0]["rows"]}
        self.assertEqual(produits["TOTAL PRODUITS TAXABLES"], Decimal("1309456357"))
        self.assertEqual(produits["TOTAL PRODUITS EXEMPTES"], Decimal("9575323"))
        self.assertEqual(produits["TOTAL PRODUITS"], Decimal("1319031680"))
        self.assertTrue(sections[1]["rows"][0][2].startswith("99.274"))
        lines = {row[0]: row for row in sections[2]["rows"]}
        self.assertEqual(lines["TVA SUR ACHATS MARCHANDISES"][3], Decimal("114794644"))  # goods: 100% recoverable
        self.assertEqual(lines["TVA SUR ACHATS MARCHANDISES"][4], 0)
        total = lines["TOTAL"]
        self.assertEqual(total[2], Decimal("130147137"))
        self.assertLess(abs(total[3] - Decimal("130035688")), 20)
        self.assertEqual(total[3] + total[4], total[2])
        pay = {row[0]: row[2] for row in sections[3]["rows"]}
        self.assertLess(abs(pay["TVA A PAYER (négatif = crédit)"] - Decimal("-7567575")), 20)

    def test_requires_all_currencies(self):
        with self.assertRaises(ValueError): vat_return.recoverable_rate_sheet({**self.result, "currency_filter": "USD"}, {})


if __name__ == "__main__":
    unittest.main()
