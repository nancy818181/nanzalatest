"""Asset accounts with a depreciation %, monthly depreciation table, one entry per account and month."""
import tempfile
import unittest
from pathlib import Path

import fixed_assets
from database import Database


class AssetDepreciationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.folder.name) / "a.db"); self.db.initialize("secret-password-1"); self.user = 1
        fixed_assets.save_category(self.db, {"account_code": "2244", "name": "Vehicles", "annual_rate": "20", "depreciation_account": "681", "accumulated_account": "2824"}, self.user)
        for code, name, day, cost in (("FA-1", "Pickup truck", "15-01-2026", "12000"), ("FA-2", "Van", "01-03-2026", "6000")):
            fixed_assets.save_asset(self.db, {"asset_code": code, "name": name, "acquired_on": day, "start_on": day, "currency": "USD", "cost": cost, "residual": "0", "useful_months": "60",
                                              "annual_rate": "20", "asset_account": "2244", "depreciation_account": "681", "accumulated_account": "2824"}, user_id=self.user)

    def tearDown(self): self.folder.cleanup()

    def test_monthly_table_and_one_entry_per_account(self):
        group = fixed_assets.monthly_table(self.db, "31-03-2026")["groups"][0]
        rows = {a["code"]: a for a in group["assets"]}
        self.assertEqual([float(rows["FA-1"][k]) for k in ("value", "old", "current", "total", "net")], [12000, 400, 200, 600, 11400])
        self.assertEqual((float(rows["FA-2"]["current"]), float(group["to_post"])), (100, 300))
        with self.assertRaisesRegex(ValueError, "earlier months"): fixed_assets.post_category_month(self.db, "2244", "31-03-2026", self.user)
        for month in ("31-01-2026", "28-02-2026"): fixed_assets.post_category_month(self.db, "2244", month, self.user)
        result = fixed_assets.post_category_month(self.db, "2244", "31-03-2026", self.user)
        self.assertEqual((result["amount"], result["assets"]), (300, 2))
        lines = [(r["account_code"], r["debit"], r["credit"]) for r in self.db.journal() if r["entry_number"] == result["voucher"]]
        self.assertEqual(sorted(lines), [("2824", 0.0, 300.0), ("681", 300.0, 0.0)])
        with self.assertRaisesRegex(ValueError, "already posted"): fixed_assets.post_category_month(self.db, "2244", "31-03-2026", self.user)

    def test_same_asset_account_keeps_currencies_and_posting_accounts_separate(self):
        fixed_assets.save_asset(self.db,{"asset_code":"LBP-1","name":"LBP equipment","acquired_on":"01-01-2026","start_on":"01-01-2026",
            "currency":"LBP","cost":"8950000","residual":"0","useful_months":60,"annual_rate":"20","asset_account":"2244",
            "depreciation_account":"681","accumulated_account":"2824"},user_id=self.user)
        fixed_assets.save_asset(self.db,{"asset_code":"USD-OTHER","name":"Other posting accounts","acquired_on":"01-01-2026","start_on":"01-01-2026",
            "currency":"USD","cost":"1200","residual":"0","useful_months":60,"annual_rate":"20","asset_account":"2244",
            "depreciation_account":"6811","accumulated_account":"2811"},user_id=self.user)
        table=fixed_assets.monthly_table(self.db,"31-01-2026","2244")
        self.assertEqual(len(table["groups"]),3)
        result=fixed_assets.post_category_month(self.db,"2244","31-01-2026",self.user)
        self.assertIsNone(result["amount"])  # No meaningless USD + LBP grand total.
        self.assertEqual(result["amounts"],{"LBP":149166.67,"USD":220.0})
        self.assertEqual(len(result["vouchers"]),3)
        with self.db.connect() as c:
            rows=[dict(r) for r in c.execute("SELECT a.asset_code,a.currency asset_currency,e.currency entry_currency,p.amount FROM fixed_asset_postings p JOIN fixed_assets a ON a.id=p.asset_id JOIN journal_entries e ON e.id=p.entry_id")]
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row["asset_currency"]==row["entry_currency"] for row in rows))
        self.assertEqual(self.db.unbalanced_entries(),[])
        lines=[r for r in self.db.journal() if r["entry_number"] in result["vouchers"]]
        self.assertTrue(any(r["account_code"]=="6811" and r["debit"]==20 for r in lines))
        with self.assertRaisesRegex(ValueError,"already posted"):
            fixed_assets.post_category_month(self.db,"2244","31-01-2026",self.user)

    def test_posting_link_failure_rolls_back_the_journal_voucher(self):
        import sqlite3
        with self.db.connect() as c:
            c.execute("CREATE TRIGGER stop_asset_link BEFORE INSERT ON fixed_asset_postings BEGIN SELECT RAISE(ABORT,'simulated asset link failure'); END")
            before=c.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
        for post in (lambda:fixed_assets.post_category_month(self.db,"2244","31-01-2026",self.user),
                     lambda:fixed_assets.post_period(self.db,fixed_assets.list_assets(self.db)[0]["id"],"31-01-2026",self.user)):
            with self.assertRaisesRegex(sqlite3.IntegrityError,"simulated asset link failure"):post()
            with self.db.connect() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0],before)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM fixed_asset_postings").fetchone()[0],0)

    def test_depreciation_voucher_cannot_be_changed_independently_of_the_asset(self):
        result=fixed_assets.post_category_month(self.db,"2244","31-01-2026",self.user)
        with self.db.connect() as c:
            voucher=dict(c.execute("SELECT id FROM journal_entries WHERE entry_number=?",(result["voucher"],)).fetchone())
        with self.assertRaisesRegex(ValueError,"linked to fixed-asset depreciation"):
            self.db.save_journal_voucher({"entry_date":"31-01-2026","description":"Changed","currency":"USD"},
                [{"account_code":"681","debit":"100"},{"account_code":"2824","credit":"100"}],self.user,entry_id=voucher["id"])
        with self.assertRaisesRegex(ValueError,"linked to fixed-asset depreciation"):
            self.db.delete_journal_voucher(voucher["id"],self.user)
        self.assertTrue(fixed_assets.schedule(self.db,fixed_assets.list_assets(self.db)[0]["id"])[0]["posted"])

    def test_asset_validation_and_configured_currency(self):
        payload={"asset_code":"CHECK-1","name":"Validation","acquired_on":"01-01-2026","start_on":"01-01-2026",
                 "currency":"USD","cost":"1200","residual":"0","useful_months":12,
                 "asset_account":"2244","depreciation_account":"681","accumulated_account":"2824"}
        with self.assertRaisesRegex(ValueError,"whole number"):
            fixed_assets.save_asset(self.db,{**payload,"useful_months":12.5},user_id=self.user)
        for field,account in (("asset_account","681"),("depreciation_account","2244"),("accumulated_account","681")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,"must be class"):
                    fixed_assets.save_asset(self.db,{**payload,field:account},user_id=self.user)
        self.db.save_currency("GBP","British Pound",self.user)
        asset=fixed_assets.save_asset(self.db,{**payload,"currency":"GBP"},user_id=self.user)
        self.assertEqual(asset["currency"],"GBP")
        invoice=self.db.create_manual_invoice({"invoice_number":"REVIEW-ASSET","invoice_date":"01-01-2026","party_name":"Supplier",
            "kind":"assets","status":"review","currency":"USD","expense_account":"2244"},
            [{"description":"Equipment","quantity":1,"unit_price":1200}],self.user)
        invoice_id=invoice["id"] if isinstance(invoice,dict) else int(invoice)
        with self.assertRaisesRegex(ValueError,"posted Assets"):
            fixed_assets.save_asset(self.db,{**payload,"asset_code":"CHECK-2","invoice_id":invoice_id},user_id=self.user)

    def test_linked_asset_purchase_cannot_disappear_from_the_books(self):
        invoice={"invoice_number":"ASSET-LINK","invoice_date":"01-01-2026","party_name":"Supplier","kind":"assets",
                 "status":"posted","currency":"USD","expense_account":"2244"}
        lines=[{"description":"Equipment","quantity":1,"unit_price":1200}]
        saved=self.db.create_manual_invoice(invoice,lines,self.user)
        invoice_id=saved["id"] if isinstance(saved,dict) else int(saved)
        asset=fixed_assets.save_asset(self.db,{"asset_code":"LINKED","name":"Equipment","acquired_on":"01-01-2026","start_on":"01-01-2026",
            "currency":"USD","cost":"1200","residual":"0","useful_months":60,"annual_rate":"20","asset_account":"2244",
            "depreciation_account":"681","accumulated_account":"2824","invoice_id":invoice_id},user_id=self.user)
        for action in (lambda:self.db.cancel_invoice(invoice_id,"Correction",self.user),
                       lambda:self.db.delete_invoice(invoice_id,self.user),
                       lambda:self.db.replace_manual_invoice(invoice_id,invoice,lines,self.user),
                       lambda:self.db.update_invoice(invoice_id,{**invoice,"subtotal":1200,"vat":0,"total":1200},self.user)):
            with self.assertRaisesRegex(ValueError,"linked to active fixed asset"):action()
        with self.assertRaisesRegex(ValueError,"linked to active fixed assets"):
            self.db.clear_invoices(self.user,make_backup=False)
        fixed_assets.delete_asset(self.db,asset["id"],self.user)
        self.db.cancel_invoice(invoice_id,"Correction after removing the unposted asset",self.user)

    def test_net_value_never_negative_and_validation(self):
        late = fixed_assets.monthly_table(self.db, "31-12-2035")["groups"][0]
        self.assertTrue(all(float(a["net"]) >= 0 and float(a["current"]) == 0 for a in late["assets"]))
        with self.assertRaisesRegex(ValueError, "between 0 and 100"): fixed_assets.save_category(self.db, {"account_code": "2244", "name": "X",
                "annual_rate": "150", "depreciation_account": "681", "accumulated_account": "2824"})
        with self.assertRaisesRegex(ValueError, "not in the chart"): fixed_assets.save_category(self.db, {"account_code": "9999999", "name": "X",
                "annual_rate": "10", "depreciation_account": "681", "accumulated_account": "2824"})
        with self.assertRaisesRegex(ValueError, "still use"): fixed_assets.delete_category(self.db, "2244")


if __name__ == "__main__":
    unittest.main()
