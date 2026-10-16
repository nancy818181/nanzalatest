import tests_setup  # noqa: F401
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from database import Database
import financial_statements as fs
import report_export as rx


class FinancialReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Database(Path(self.temp.name)/'books.db');self.db.initialize('example-only-123');self.addCleanup(self.db.release)
        self.db.save_journal_voucher({'entry_date':'01-03-2026','currency':'USD','description':'Example'},
            [{'account_code':'531','debit':'100','credit':0},{'account_code':'7011','debit':0,'credit':'100'}],1)

    def pack(self,**options):
        return fs.build({2026:self.db},{'years':'2026','basis':'USD','auditor_report':False,**options})

    def test_manual_cash_flow_difference_is_reported(self):
        fs.save_config(self.db,{'basis':'USD','supplements':{'cf_operating':'90','cf_investing':'0','cf_financing':'0'}},1)
        pack=self.pack();checks=next(s for s in pack['sections'] if s['kind']=='checks')
        self.assertEqual(checks['rows'][0][1],Decimal('0'))
        self.assertEqual(checks['rows'][1][1],Decimal('10'))
        self.assertIn('cash flow does not reconcile',str(pack))

    def test_complete_cash_flow_with_exchange_effect_reconciles(self):
        fs.save_config(self.db,{'basis':'USD','supplements':{'cf_operating':'90','cf_investing':'0','cf_financing':'0','cf_fx':'10'}},1)
        checks=next(s for s in self.pack()['sections'] if s['kind']=='checks')
        self.assertEqual(checks['rows'][1][1],0)

    def test_incomplete_override_does_not_silently_take_effect(self):
        fs.save_config(self.db,{'basis':'USD','supplements':{'cf_operating':'90'}},1)
        self.assertIn('incomplete cash flow overrides were ignored',str(self.pack()))

    def test_opposite_unmapped_balances_do_not_cancel_the_warning(self):
        for code in ('901000001','902000001'):
            self.db.save_account({'code':code,'name_en':f'Unclassified {code}','type':'asset'},1)
        self.db.save_journal_voucher({'entry_date':'02-03-2026','currency':'USD','description':'Unmapped'},
            [{'account_code':'901000001','debit':'75','credit':0},{'account_code':'902000001','debit':0,'credit':'75'}],1)
        pack=self.pack();checks=next(s for s in pack['sections'] if s['kind']=='checks')
        self.assertEqual(checks['rows'][2][1],Decimal('150'))
        self.assertIn('gross balance 150',str(pack))

    def test_standalone_report_is_available_without_audit_or_notes(self):
        pack=fs.reconciliation_report({2026:self.db},{'years':'2026','language':'ar'})
        self.assertEqual(pack['title'],'مطابقة البيانات المالية')
        self.assertEqual({s['kind'] for s in pack['sections']},{'checks','review'})

    def test_print_headers_and_notes_do_not_repeat_entire_narratives(self):
        pack=self.pack();path=Path(self.temp.name)/'report.xlsx'
        rx.export_sections_excel(path,pack['title'],pack['meta'],pack['sections'])
        from openpyxl import load_workbook
        book=load_workbook(path)
        self.addCleanup(book.close)
        self.assertEqual(book['Financial Position'].print_title_rows,'$1:$4')
        self.assertEqual(book['Notes'].print_title_rows,'$1:$1')
        self.assertEqual(book['Financial Position'].freeze_panes,'B5')
        self.assertTrue(book['Financial Position'].print_area)

    def test_exact_large_amount_formatting_does_not_round_through_float(self):
        value=Decimal('9007199254740993.25')
        self.assertEqual(rx._formatted(value),'9,007,199,254,740,993.25')
        self.assertEqual(rx._accounting_text(-value),'(9,007,199,254,740,993.25)')
        self.assertEqual(rx._plain(value),'9007199254740993.25')

    def test_arabic_pdf_column_order_does_not_depend_on_ui_language(self):
        pack=self.pack(language='ar');rx._load_libraries();tables=[];real_table=rx.Table
        def capture(data,*args,**kwargs):
            if data and len(data[0])==3:tables.append(data)
            return real_table(data,*args,**kwargs)
        with patch('report_export.arabic_reports',return_value=False),patch('report_export.Table',side_effect=capture):
            rx.export_sections_pdf(Path(self.temp.name)/'arabic.pdf',pack['title'],pack['meta'],pack['sections'])
        statement=next(table for table in tables if hasattr(table[0][0],'getPlainText') and table[0][0].getPlainText()=='31-12-2026 (USD)')
        self.assertEqual(statement[0][-1].text,'')


class FinancialScreenTest(unittest.TestCase):
    def test_export_carries_company_period_currency_and_account_scope(self):
        from desktop_reports import ReportsMixin
        field=lambda value:SimpleNamespace(get=lambda:value)
        app=SimpleNamespace(client=SimpleNamespace(settings=lambda:{'company_name':'Example SARL'}),
            financial_report_range=lambda:['2026-01-01','2026-12-31'],view_currency=field('USD'),
            report_account_from=field('531'),report_account_to=field('531'),financial_filter_sets=lambda:{},
            ledger_rows=[{'entry_date':'01-03-2026','entry_number':'JV-1','account_code':'531','currency':'USD',
                          'account_name':'Cash','description':'Example','debit':100,'credit':0,'balance':100}],output_sections=Mock())
        ReportsMixin.financial_report_export(app,'ledger','pdf')
        args=app.output_sections.call_args.args
        self.assertIn('Example SARL',args[1]);self.assertIn('Currency: USD',args[1])
        self.assertIn('Account range: 531 to 531',args[1])
        self.assertEqual(len(args[2][0]['column_weights']),len(args[2][0]['headers']))

    def test_balance_screen_applies_the_same_account_range_as_export(self):
        from desktop_reports import ReportsMixin
        field=lambda value:SimpleNamespace(get=lambda:value)
        row=lambda code:{'type':'asset','code':code,'currency':'USD','name_en':code,'debit':100,'credit':0,'balance':100}
        client=SimpleNamespace(general_ledger=lambda *args:{'items':[]},balance_sheet=lambda *args:[row('101'),row('531')],
                               vat_report=lambda *args:{'items':[],'summary':[]},cash_flow=lambda *args:[],comparative_reports=lambda *args:{'items':[]})
        trees={key:Mock() for key in ('ledger_tree','balance_tree','vat_tree','cash_tree','comparative_tree')}
        for tree in trees.values():tree.get_children.return_value=[]
        app=SimpleNamespace(client=client,financial_report_range=lambda:['2026-01-01','2026-12-31'],
            view_currency=field('USD'),report_account_from=field('531'),report_account_to=field('531'),can_use=lambda key:True,
            refresh_financial_filter_choices=Mock(),financial_filter_sets=lambda:{},financial_filter_ok=lambda *args:True,
            vat_summary=Mock(),**trees)
        with patch('desktop_common.fill_tree'):
            ReportsMixin.load_financial_reports(app)
        self.assertEqual([r['code'] for r in app.balance_rows],['531'])
        self.assertEqual(app.balance_tree.insert.call_count,1)
        self.assertEqual(app.balance_tree.insert.call_args.kwargs['values'][1],'531')
