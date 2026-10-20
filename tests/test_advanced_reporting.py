"""Posted-ledger report layouts and evidence-based cost-center VAT components."""
import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import nanza_paths  # noqa: F401
from database import Database
from ledger_reports import _load_lines
from nanza.reports.analytic_study import _with_vat_evidence, analyze_rows, build_study
from nanza.reports.analytic_report import build_report as analytic_report
from nanza_delivery.custom_report_builder import (
    build_ledger_report, build_report, export_report, list_templates,
    reorder_layout, save_template, validate_definition,
)


def layout(**changes):
    return dict(version=1, kind='pnl', date_from='2026-01-01', date_to='2026-12-31',
                group_by=['department', 'project', 'account'], columns=['amount', 'balance'],
                currencies=['native'], **changes)


class LayoutTests(unittest.TestCase):
    def test_desktop_numeric_columns_follow_dynamic_layout(self):
        from nanza.ui.desktop_workbench import CustomReportWindow
        result={'headers':['project','account','Currency','balance','amount'],
                'definition':{'columns':['balance','amount']},
                'rows':[['P1','626340001','USD','111','-111']]}
        rows=CustomReportWindow.report_rows(None,result)
        self.assertEqual(rows[0][:3],['P1','626340001','USD'])
        self.assertEqual(rows[0][3:],[Decimal('111'),Decimal('-111')])

    def test_drag_order_preserved_and_input_unchanged(self):
        original = layout()
        reordered = reorder_layout(original, 'group_by', 0, 2)
        self.assertEqual(reordered['group_by'], ['project', 'account', 'department'])
        self.assertEqual(original['group_by'], ['department', 'project', 'account'])

    def test_schema_rejects_sql_and_invalid_codes_or_currencies(self):
        for changes in ({'sql': 'DELETE FROM journal_lines'}, {'account_codes': ['6263.4']},
                        {'currencies': ['native', 'USD']}, {'group_by': ['project']},
                        {'columns': ['amount', 'amount']}, {'kind': 'arbitrary'},
                        {'version': 2}, {'currencies': ['USD);DROP']}, {'date_to': '2027-01-01'}):
            definition = layout()
            definition.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_definition(definition)

    def test_cross_reference_signed_components_are_subsets(self):
        lines = [dict(iso_date='2026-01-02', code='626340001', account_type='expense',
                      department_code='D1', department_name='Store', project_code='P1',
                      branch_name='Beirut', signed={'USD': amount}, id=index,
                      vat_component=index > 0, vat_provenance='posted_vat_reclass', vat_category='EDL')
                 for index, amount in enumerate((100, 11, -11))]
        before = copy.deepcopy(lines)
        study = analyze_rows(lines, currency='USD')
        center = study['cost_centers']['summaries'][0]
        self.assertEqual(center['expense_cost'], 100)
        self.assertEqual(center['capitalized_vat'], 0)
        self.assertEqual(center['vat_by_category']['EDL'], 0)
        self.assertEqual(center['expense_excluding_identified_vat'], 100)
        self.assertEqual(lines, before)
        sections = analytic_report(study)['sections']
        self.assertIn('cost_center_cross_reference', {s['key'] for s in sections})
        self.assertIn('EDL VAT', next(s for s in sections if s['key']=='cost_center_summary')['headers'])
        arabic = analytic_report(study, {'language': 'ar'})
        self.assertIn('مراكز الكلفة', next(s for s in arabic['sections'] if s['key']=='cost_center_summary')['heading'])

    def test_missing_equivalent_is_never_treated_as_zero(self):
        with self.assertRaisesRegex(ValueError, 'Missing EUR'):
            analyze_rows([dict(code='626340001', account_type='expense', signed={'USD': 100})], currency='EUR')

    def test_nonposted_analytic_rows_are_excluded(self):
        study = analyze_rows([dict(code='626340001', account_type='expense', posting_status='rejected', signed={'USD': 100})])
        self.assertEqual(study['cost_centers']['summaries'], [])


class LedgerReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / 'test.db')
        self.db.initialize('Report-tests-2026!')
        self.addCleanup(self.db.release)
        for code, name, kind in [('626340001','EDL Electricity','expense'), ('701100001','Sales','income'),
                                  ('531000001','Cash','asset'), ('401100001','Supplier','liability')]:
            if not any(a['code'] == code for a in self.db.list_accounts()):
                self.db.save_account({'code':code,'name_en':name,'type':kind},1)
        self.department = self.db.save_department({'code':'D1','name':'Store'},1)['id']
        self.project = self.db.save_project({'code':'P1','name':'Office'},1)['id']

    def voucher(self, debit='626340001', credit='531000001', amount='100', **header):
        return self.db.save_journal_voucher(
            {'entry_date':'2026-01-02','currency':'USD','description':'Report test',**header},
            [{'account_code':debit,'debit':amount, 'department_id':self.department,'project_id':self.project},
             {'account_code':credit,'credit':amount}],1)

    def snapshot(self):
        with self.db.connect() as c:
            return [[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')]
                    for t in ('accounts','journal_entries','journal_lines')]

    def test_pnl_and_layout_read_only_native_totals(self):
        self.voucher()
        self.voucher(debit='531000001',credit='701100001',amount='150')
        before = self.snapshot()
        report = build_ledger_report(self.db,layout())
        self.assertEqual(report['currency_summaries']['USD']['net_profit'],Decimal('50'))
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(len(r['dimensions'][-1])==9 for r in report['records']))
        self.assertEqual(report['totals_scope'],'complete_filtered_ledger')

    def test_rejected_and_draft_do_not_leak(self):
        self.voucher()
        self.db.save_journal_voucher({'entry_date':'2026-01-02','currency':'USD','description':'Rejected'},
            [{'account_code':'626340001','debit':'900'},{'account_code':'531000001','credit':'900'}],1,defer_posting=True)
        with self.db.connect() as c:
            c.execute("UPDATE journal_entries SET posting_status='rejected' WHERE id=(SELECT MAX(id) FROM journal_entries)")
        report=build_ledger_report(self.db,layout())
        self.assertEqual(report['totals']['USD'],Decimal('-100'))

    def test_multi_currency_separation_and_conversion(self):
        self.voucher()
        self.voucher(amount='20',currency='EUR')
        native=build_ledger_report(self.db,layout())
        self.assertEqual(native['totals'],{'EUR':Decimal('-20'),'USD':Decimal('-100')})
        definition=layout();definition['currencies']=['USD','LBP'];definition['account_codes']=['626340001']
        # Unavailable rates must fail; no implicit rate of one.
        with self.assertRaises(ValueError):
            build_ledger_report(self.db,definition)

    def test_reporting_currency_columns_use_explicit_rates(self):
        self.voucher()
        self.db.save_exchange_rate({'rate_date':'2026-01-02','from_currency':'USD','to_currency':'LBP','rate':'89500'},1)
        definition=layout();definition['currencies']=['USD','LBP']
        report=build_ledger_report(self.db,definition)
        self.assertEqual(report['totals']['USD'],Decimal('-100'))
        self.assertEqual(report['totals']['LBP'],Decimal('-8950000'))
        self.assertEqual(len(report['records']),2)

    def test_balance_as_at_keeps_earlier_movements(self):
        self.voucher(debit='531000001',credit='401100001',entry_date='2026-01-01')
        definition=layout();definition.update(kind='balance',date_from='2026-02-01')
        report=build_ledger_report(self.db,definition)
        self.assertEqual(report['currency_summaries']['USD']['debit'],Decimal('100'))
        self.assertEqual(report['currency_summaries']['USD']['credit'],Decimal('100'))

    def test_unknown_account_and_bad_currency_rejected(self):
        for change in ({'account_codes':['699999999']},{'currencies':['ZZZ']}):
            definition=layout();definition.update(change)
            with self.assertRaises(ValueError): build_ledger_report(self.db,definition)

    def test_legacy_codes_disclosed_without_renumbering(self):
        self.voucher(debit='6263.4')
        report=build_ledger_report(self.db,layout())
        self.assertIn('6263.4',report['excluded_legacy_account_codes'])
        self.assertEqual(report['rows'],[])

    def test_template_api_dispatch_paging_and_export(self):
        self.voucher()
        self.voucher(debit='531000001',credit='701100001',amount='120')
        definition=layout()
        filters={'date_from':definition['date_from'],'date_to':definition['date_to'],'definition':json.dumps(definition)}
        first=build_report(self.db,filters,limit=1)
        self.assertTrue(first['has_more'])
        self.assertEqual(first['totals']['USD'],Decimal('20'))
        exported=export_report(self.db,filters)
        self.assertEqual(len(exported['rows']),2)
        self.assertEqual(exported['totals']['USD'],Decimal('20'))
        save_template(self.db,1,'P&L layout',filters)
        stored=list_templates(self.db,1)[0]['filters']
        self.assertEqual(json.loads(stored['definition'])['group_by'],definition['group_by'])
        self.assertEqual(list_templates(self.db,2),[])

    def test_vat_reclass_inherits_document_dimensions_without_double_count(self):
        self.db.add_expense({'expense_date':'2026-01-02','description':'EDL electricity',
            'category':'EDL','currency':'USD','subtotal':'100','vat':'11',
            'expense_account':'626340001','payment_account':'531000001',
            'department_id':self.department,'project_id':self.project,'vat_recoverable':False},1)
        before=self.snapshot()
        study=build_study(self.db,'2026-01-01','2026-12-31')
        self.assertEqual(self.snapshot(),before)
        center=next(r for r in study['cost_centers']['summaries'] if r['department_code']=='D1')
        self.assertEqual(center['expense_cost'],111)
        self.assertEqual(center['capitalized_vat'],11)
        self.assertEqual(center['expense_excluding_identified_vat'],100)
        self.assertEqual(center['vat_by_category']['EDL'],11)
        self.assertTrue(study['pnl_check']['matches'])

    def test_all_four_vat_categories_are_expanded(self):
        for category in ('EDL','TEL','CELL','FUEL'):
            self.db.add_expense({'expense_date':'2026-01-02','description':category,
                'category':category,'currency':'USD','subtotal':'100','vat':'11',
                'expense_account':'626340001','payment_account':'531000001',
                'department_id':self.department,'vat_recoverable':False},1)
        study=build_study(self.db,'2026-01-01','2026-12-31')
        center=next(r for r in study['cost_centers']['summaries'] if r['department_code']=='D1')
        self.assertEqual(center['expense_cost'],444)
        self.assertEqual(center['capitalized_vat'],44)
        for category in ('EDL','TEL','CELL','FUEL'):
            self.assertEqual(center['vat_by_category'][category],11)

    def test_vat_reversal_removes_identified_component(self):
        self.test_vat_reclass_inherits_document_dimensions_without_double_count()
        with self.db.connect() as c:
            entry=c.execute("SELECT id FROM journal_entries WHERE source_type='vat_reclass'").fetchone()[0]
        with self.db.connect() as c:
            lines=[{'account_code':r['code'],'debit':r['credit'],'credit':r['debit']} for r in c.execute(
                'SELECT a.code,j.debit,j.credit FROM journal_lines j JOIN accounts a ON a.id=j.account_id WHERE j.entry_id=?',(entry,))]
        self.db.save_journal_voucher({'entry_date':'2026-02-01','currency':'USD','description':'VAT reversal'},lines,1,reversal_of=entry)
        study=build_study(self.db,'2026-01-01','2026-12-31')
        self.assertEqual(sum(r['capitalized_vat'] for r in study['cost_centers']['summaries']),0)

    def test_multiple_dimensions_are_not_guessed(self):
        self.test_vat_reclass_inherits_document_dimensions_without_double_count()
        other=self.db.save_department({'code':'D2','name':'Other'},1)['id']
        with self.db.connect() as c:
            c.execute("UPDATE journal_lines SET department_id=? WHERE entry_id IN (SELECT id FROM journal_entries WHERE source_type='expense')",(other,))
        rows=_with_vat_evidence(self.db,_load_lines(self.db,{'first_column':'USD','second_column':'none'}))
        vat=next(r for r in rows if r.get('vat_component'))
        self.assertEqual(vat['department_code'],'')
        self.assertEqual(vat['vat_dimension_status'],'unallocated')
