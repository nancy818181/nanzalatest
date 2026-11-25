"""Dashboard totals keep their meaning while SQLite aggregates the source rows."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from database import Database


class DashboardAggregationTest(unittest.TestCase):
    def test_posted_ledger_profit_allocations_returns_and_draft_exclusion(self):
        from decimal import Decimal
        with TemporaryDirectory() as folder:
            data=Database(Path(folder)/'posted-dashboard.db');data.initialize('Synthetic-Dashboard-2026!')
            self.addCleanup(data.release)
            customer=data.save_party({'kind':'customer','name':'Dashboard customer','currency':'USD'},1)
            supplier=data.save_party({'kind':'supplier','name':'Dashboard supplier','currency':'USD'},1)
            def invoice(kind,party,quantity,number,status='posted'):
                return data.create_manual_invoice({'invoice_number':number,'invoice_date':'2026-01-10','party_name':party['name'],'kind':kind,'currency':'USD','status':status},[{'description':number,'quantity':quantity,'unit_price':'10','vat_rate':'11'}],1)
            sale=invoice('sale',customer,10,'DASH-S');purchase=invoice('purchase',supplier,5,'DASH-P')
            for kind,party,iid,amount in [('customer_receipt',customer,sale,'40'),('supplier_payment',supplier,purchase,'20')]:
                payment=data.add_payment({'kind':kind,'payment_date':'2026-01-20','party_id':party['id'],'currency':'USD','amount':amount,'cash_account':'531','party_account':party['account_number']},1)
                data.save_allocations(payment,[{'invoice_id':iid,'amount':amount}],1)
            for iid,quantity,key in [(sale,'2','DASH-R-S'),(purchase,'1','DASH-R-P')]:
                line=data.invoice_detail(iid)['items'][0]
                data.create_invoice_return(iid,[{'item_id':line['id'],'quantity':quantity}],'2026-02-01',1,key)
            data.save_journal_voucher({'entry_date':'2026-02-05','currency':'USD','description':'Dashboard adjustment'},[{'account_code':'601100000','debit':'5','credit':'0'},{'account_code':'531','debit':'0','credit':'5'}],1)
            invoice('sale',customer,999,'DASH-DRAFT','review')
            actual=next(r for r in data.professional_dashboard()['metrics'] if r['currency']=='USD')
            # Literal document arithmetic: sales 100-20; costs 50-10+5;
            # AR (100-20)*1.11-40; AP (50-10)*1.11-20.
            for field,wanted in {'sales':'80','purchases':'40','expenses':'45','profit':'35','receivables':'48.80','payables':'24.40'}.items():
                self.assertEqual(Decimal(str(actual[field])),Decimal(wanted),field)

    def test_multiple_currencies_expenses_and_overdue_exclude_cancelled(self):
        with TemporaryDirectory() as folder:
            data = Database(Path(folder) / "dashboard.db")
            with data.connect() as db:
                db.executescript("""
                    CREATE TABLE invoices (
                        kind TEXT, currency TEXT, subtotal TEXT, total TEXT,
                        amount_paid TEXT, due_date TEXT, status TEXT, invoice_date TEXT
                    );
                    CREATE TABLE expenses (currency TEXT, subtotal TEXT);
                """)
                db.executemany("INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)", [
                    ("sale","USD","100","111","20","01-01-2000","posted","15-01-2026"),
                    ("sale","USD","50","55","55","01-01-2000","posted","20-01-2026"),
                    ("purchase","USD","40","44","4",None,"posted","20-01-2026"),
                    ("sale","EUR","25","27.75","0",None,"posted","20-02-2026"),
                    ("sale","USD","999","999","0","01-01-2000","cancelled","20-02-2026"),
                ])
                db.executemany("INSERT INTO expenses VALUES(?,?)", [("USD","5"),("USD","8")])
            # A dashboard read should not pull every expense row through list_expenses.
            data.list_expenses = lambda: self.fail("full expense rows were loaded")
            result = data.professional_dashboard()
            by_currency = {row["currency"]: row for row in result["metrics"]}
            self.assertEqual(by_currency["USD"], {
                "currency":"USD","sales":150.0,"purchases":40.0,"expenses":13.0,
                "profit":97.0,"receivables":91.0,"payables":40.0,"overdue":1
            })
            self.assertEqual(by_currency["EUR"]["sales"],25.0)
            self.assertEqual(by_currency["EUR"]["overdue"],0)
            self.assertEqual(len(result["monthly"]),3)


class TabLoadingTest(unittest.TestCase):
    def test_selecting_one_tab_does_not_build_every_pending_page(self):
        from types import SimpleNamespace
        from desktop import SaberApp

        dashboard=object(); invoice_page=object(); reports=object()
        def frame_for(page):
            return SimpleNamespace(master=SimpleNamespace(master=page))
        calls=[]
        def build_invoices(): calls.append("invoices")
        def build_financial_reports(): calls.append("reports")
        app=SimpleNamespace(main_tab_pages=[dashboard,invoice_page,reports],
            invoices_tab=frame_for(invoice_page),reports_tab=frame_for(reports),
            _pending_builders=[build_invoices,build_financial_reports])
        app._run_page_builder=lambda builder:builder()
        SaberApp._ensure_main_tab(app,invoice_page)
        self.assertEqual(calls,["invoices"])
        self.assertEqual([item.__name__ for item in app._pending_builders],["build_financial_reports"])


if __name__ == "__main__":
    unittest.main()
