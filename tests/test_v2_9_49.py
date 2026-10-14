"""2.9.49: VAT periodic declaration Q1-2 with annexes Q11-2 (partial deduction, Art. 31) and Q13-2; ratio includes
revenues outside the scope; reports keep their columns; journal rows carry project / department."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import vat_return
from database import Database
from report_export import tidy_sections


class VatOfficialFormTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c_2026.db"); self.db.initialize("secret")
        self.user = self.db.user_for_token(self.db.login("admin", "secret")["token"])["id"]

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()

    def doc(self, number, kind, amount, vat_rate=11, **extra):
        item = {"invoice_number": number, "invoice_date": "15-05-2026", "party_name": extra.pop("party", "Client A" if kind == "sales" else "Supplier B"),
                "kind": kind, "currency": "LBP", "status": "posted", "payment_method": "On Account (Not Cash)",
                "supplier_account": "411100001" if kind == "sales" else "401100001", "vat_account": "4427" if kind == "sales" else "442660000",
                "expense_account": "711000001" if kind == "sales" else "601100000"}
        item.update(extra)
        return self.db.create_manual_invoice(item, [{"description": "x", "quantity": 1, "unit_price": amount, "vat_rate": vat_rate}], self.user)

    def form(self):
        result = vat_return.json_ready(vat_return.build_vat_return(self.db, 2026, 2))
        meta, sections = vat_return.official_form(result, {"company_name": "Demo", "company_mof": "123"})
        boxes = {row[0]: row for section in sections[:3] for row in section["rows"]}
        return result, sections, boxes

    def test_boxes_annex_and_partial_deduction(self):
        self.doc("S-1", "sales", 1000000)                                                           # taxable 11%
        self.doc("S-2", "sales", 500000, vat_rate=0, vat_treatment="out_of_scope")                  # outside the scope
        self.doc("P-1", "purchases", 200000, vat_use="taxable")                                      # only deductible ops
        self.doc("P-2", "purchases", 300000, vat_use="mixed")                                        # use cannot be determined
        result, sections, boxes = self.form()
        ratio = Decimal(str(result["deduction_ratio"]))
        self.assertEqual(ratio, Decimal("0.666667"))  # 1,000,000 / (1,000,000 + 500,000): outside the scope is in the denominator
        self.assertEqual((boxes["100"][3], boxes["100"][4]), (Decimal(1000000), Decimal(110000)))
        self.assertEqual(boxes["150"][3], Decimal(500000))
        self.assertEqual((boxes["600"][3], boxes["600"][4]), (Decimal(200000), Decimal(22000)))
        self.assertEqual(boxes["620"][3], Decimal(300000)); self.assertEqual(boxes["620"][4], (Decimal(33000) * ratio).quantize(Decimal("1")))
        self.assertEqual(boxes["630"][4], boxes["600"][4] + boxes["620"][4]); self.assertEqual(boxes["200"][5], boxes["630"][4])
        self.assertEqual(boxes["300"][3], Decimal(110000))
        self.assertEqual(abs(boxes["330"][3] - boxes["250"][5]) <= 1, True)  # settlement uses the same deductible VAT
        suppliers = sections[4]["rows"]; self.assertEqual(suppliers[0][1], "Supplier B")

    def test_requires_all_currencies(self):
        result = vat_return.json_ready(vat_return.build_vat_return(self.db, 2026, 2, currency="USD"))
        with self.assertRaises(ValueError): vat_return.official_form(result, {})


class ReportsKeepColumnsTest(unittest.TestCase):
    def test_only_payroll_sections_are_compacted(self):
        plain = {"heading": "Balance sheet", "headers": ["Code", "Name", "Current", "Prior"], "rows": [["1", "A", 10, 0]]}
        self.assertEqual(tidy_sections([plain])[0]["headers"], plain["headers"])
        self.assertEqual(tidy_sections([{**plain, "compact": True}])[0]["headers"], ["Code", "Name", "Current"])

    def test_journal_rows_carry_project_and_department(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret")
            rows = db.journal()
            self.assertTrue(all("project_code" in r and "department_code" in r for r in rows))
            db.release()


if __name__ == "__main__":
    unittest.main()
