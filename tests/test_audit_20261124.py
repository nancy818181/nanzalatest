"""Regression cases reproduced from the isolated 24 November accounting audit."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from database import Database
import invoice_calc


class AuditRegressionTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'synthetic.db'
        self.db=Database(self.path)
        self.db.initialize('Synthetic-audit-2026!')
        self.addCleanup(self.db.release)

    def reopen(self):
        self.db.release()
        self.db=Database(self.path)
        self.addCleanup(self.db.release)

    def test_rule_update_failure_rolls_back_after_writing_and_reopening(self):
        self.db.apply_lebanese_payroll_rules(1)
        before=self.db.list_payroll_settings()
        self.assertEqual(len(before),9)
        original=self.db.save_payroll_settings
        for fail_at in (2,5,9):
            calls=[]
            def fail(item,user):
                result=original(item,user)
                calls.append(item['date_from'])
                if len(calls)==fail_at:raise RuntimeError('Synthetic failure after write')
                return result
            with patch.object(self.db,'save_payroll_settings',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'after write'):
                    self.db.apply_lebanese_payroll_rules(1)
            self.reopen()
            self.assertEqual(self.db.list_payroll_settings(),before)
            original=self.db.save_payroll_settings
        self.db.apply_lebanese_payroll_rules(1)
        self.db.apply_lebanese_payroll_rules(1)
        self.assertEqual(len(self.db.list_payroll_settings()),9)

    def test_new_future_period_keeps_prior_rules_and_saved_payroll(self):
        self.db.apply_lebanese_payroll_rules(1)
        rules=self.db.payroll_settings_for('2026-05-31')
        employee=self.db.save_employee({'full_name':'Synthetic employee','base_salary':'10000000',
            'currency':'LBP','hire_date':'01-01-2026'},1)
        payroll=self.db.save_payroll({'employee_id':employee['id'],'period_date':'31-05-2026'},1)
        self.db.post_payroll(payroll['id'],1)
        with self.db.connect() as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM payroll_records')]
        self.db.save_payroll_settings({**rules,'date_from':'2027-01-01','date_to':None,'medical_ceiling':'999999999'},1)
        self.assertEqual(self.db.payroll_settings_for('2026-05-31')['medical_ceiling'],rules['medical_ceiling'])
        with self.db.connect() as c:self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM payroll_records')],before)
        self.assertTrue(payroll['id'])

    def test_invalid_optional_rule_value_does_not_close_previous_period(self):
        before=self.db.list_payroll_settings()
        rules=self.db.payroll_settings_for('2026-05-31')
        with self.assertRaises(ValueError):
            self.db.save_payroll_settings({**rules,'date_from':'2027-01-01','date_to':None,'minimum_wage':'invalid'},1)
        self.reopen()
        self.assertEqual(self.db.list_payroll_settings(),before)

    def test_manual_rounding_preserves_price_until_line_calculation(self):
        for price,qty,expected in [('1.005','1','1.01'),('1.005','3','3.02'),('2.675','2','5.35')]:
            with self.subTest(price=price,qty=qty):
                line={'description':'Synthetic rounding','quantity':qty,'unit_price':price,'vat_rate':'0'}
                oracle=invoice_calc.calculate([line],exact=True)['total_ht']
                self.assertEqual(oracle,Decimal(expected))
                from desktop_sales_invoice import SalesInvoiceMixin
                screen_line=SalesInvoiceMixin().recalculate_sales_item(dict(line))
                self.assertEqual(Decimal(str(screen_line['net'])),Decimal(expected))
                iid=self.db.create_manual_invoice({'invoice_date':'01-01-2026','party_name':'Synthetic customer',
                    'kind':'sale','currency':'USD'},[line],1)
                detail=self.db.invoice_detail(iid)
                self.assertEqual(Decimal(str(detail['invoice']['total'])),Decimal(expected))
                self.assertEqual(Decimal(str(detail['items'][0]['unit_price'])),Decimal(price))
        self.reopen()
        self.assertFalse(self.db.unbalanced_entries())

    def test_purchase_screen_calculates_and_saves_same_half_up_amount(self):
        from desktop_purchases import PurchasesMixin
        from types import SimpleNamespace
        class Var:
            def __init__(self,value):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value
        app=PurchasesMixin()
        row={'item_code':'SYN','name':'Synthetic precision','quantity':'3','unit_cost':'1.005','discount_percent':0,'vat_flag':'Yes'}
        app.purchase_item_total(row)
        self.assertEqual(row['total'],Decimal('3.02'))
        values={'type':'Purchases','account':'601100000','vat_account':'44210','supplier':'Synthetic supplier',
            'number':'ROUND-UI','date':'01-01-2026','due':'31-01-2026','currency':'USD','taxable':'3.02','exempt':'0','vat':'.33','rate':'11'}
        app.purchase_form={'vars':{k:Var(v) for k,v in values.items()},'discount_percent':Var('0'),
            'discount_amount':Var('0'),'discount_mode':'percent','department':Var(''),'project':Var(''),
            'use':Var('Mixed (partial deduction)'),'reverse':Var(False),'warehouse':Var('MAIN'),
            'items_sheet':SimpleNamespace(ordered=lambda:[row])}
        app.purchase_items_changed=lambda:None
        app.dimension_code=lambda value:value
        app.inventory_lookup_rows=lambda:[{'sku':'SYN'}]
        header,lines=app.purchase_payload()
        self.assertEqual(Decimal(str(lines[0]['deductible_subtotal'])),Decimal('3.02'))
        self.assertEqual(Decimal(str(lines[0]['unit_price'])),Decimal('1.005'))
        import inventory
        inventory.save_item(self.db,{'sku':'SYN','name':'Synthetic precision','unit':'unit'},1)
        iid=self.db.create_manual_invoice(header,lines,1)
        detail=self.db.invoice_detail(iid)
        self.assertEqual(Decimal(str(detail['invoice']['total'])),Decimal('3.35'))

    def test_negative_manual_values_are_rejected_without_partial_document(self):
        before=len(self.db.list_invoices())
        for price,qty in [('-1.005','1'),('1.005','-2')]:
            with self.assertRaises(ValueError):
                self.db.create_manual_invoice({'invoice_date':'01-01-2026','party_name':'Synthetic customer','kind':'sale'},
                    [{'description':'Negative','quantity':qty,'unit_price':price,'vat_rate':0}],1)
        self.assertEqual(len(self.db.list_invoices()),before)

    def test_open_allocatable_documents_exclude_draft(self):
        party=self.db.save_party({'kind':'customer','name':'Synthetic customer','currency':'USD'},1)
        ids=[]
        for status in ('review','posted'):
            ids.append(self.db.create_manual_invoice({'invoice_date':'01-01-2026','party_name':party['name'],
                'kind':'sale','currency':'USD','status':status},
                [{'description':'Synthetic','quantity':1,'unit_price':100,'vat_rate':0}],1))
        self.assertEqual([r['id'] for r in self.db.open_documents(party['id'])],[ids[1]])

    def test_logout_revokes_only_the_requested_session(self):
        one=self.db.login('admin','Synthetic-audit-2026!')['token']
        two=self.db.login('admin','Synthetic-audit-2026!')['token']
        self.db.logout(one)
        self.assertIsNone(self.db.user_for_token(one))
        self.assertIsNotNone(self.db.user_for_token(two))

    def test_ocr_implausible_date_requires_correction(self):
        import pdf_import
        result=pdf_import._require_ocr_review({'invoice_date':'15-05-5601','notes':''})
        self.assertEqual(result['invoice_date'],'')
        self.assertTrue(result['review_required'])
        self.assertTrue(any('1900' in w for w in result['review_warnings']))

    def test_q1_advance_allocated_to_q2_invoice_remains_visible_at_q1(self):
        import business_reports
        party=self.db.save_party({'kind':'customer','name':'Synthetic advance','currency':'USD'},1)
        pid=self.db.add_payment({'kind':'customer_receipt','payment_date':'15-03-2026','party_id':party['id'],
            'currency':'USD','amount':'111','cash_account':'531','party_account':party['account_number']},1)
        iid=self.db.create_manual_invoice({'invoice_date':'15-04-2026','party_name':party['name'],'kind':'sale','currency':'USD'},
            [{'description':'Final invoice','quantity':1,'unit_price':100,'vat_rate':11}],1)
        self.db.save_allocations(pid,[{'invoice_id':iid,'amount':'111'}],1)
        q1=business_reports.ageing(self.db,{'date_to':'31-03-2026','basis':'USD','fifo':False})
        summary=next(s for s in q1['sections'] if s['heading']=='Ageing summary')
        balance=next(r for r in summary['rows'] if r[0]=='NET BALANCE')
        self.assertEqual(Decimal(str(balance[1])),Decimal('-111'))
        detail=next(s for s in q1['sections'] if s['heading'].startswith('Unallocated receipts'))
        self.assertEqual(Decimal(str(detail['rows'][0][-1])),Decimal('111'))
        q2=business_reports.ageing(self.db,{'date_to':'30-06-2026','basis':'USD','fifo':False})
        summary=next(s for s in q2['sections'] if s['heading']=='Ageing summary')
        self.assertEqual(Decimal(str(next(r for r in summary['rows'] if r[0]=='NET BALANCE')[1])),0)

    def test_realized_fx_gain_loss_partial_full_repeat_and_reversal(self):
        import ledger_reports
        for kind,rate,expected in [('sale','1.2','10'),('sale','1.05','-5'),('purchase','1.2','-10'),('purchase','1.05','5')]:
            with self.subTest(kind=kind,rate=rate):
                self.db.release()
                self.db=Database(Path(self.folder.name)/f'{kind}-{rate}.db')
                self.db.initialize('Synthetic-audit-2026!')
                self.addCleanup(self.db.release)
                party=self.db.save_party({'kind':'customer' if kind=='sale' else 'supplier',
                    'name':f'Synthetic {kind} {rate}','currency':'EUR'},1)
                for day,value in [('01-01-2026','1.1'),('01-02-2026',rate)]:
                    self.db.save_exchange_rate({'date_from':day,'from_currency':'EUR','to_currency':'USD','rate':value},1)
                self.db.save_exchange_rate({'date_from':'01-01-2026','from_currency':'USD','to_currency':'LBP','rate':'89500'},1)
                self.db.__dict__.pop('_rate_state',None)
                iid=self.db.create_manual_invoice({'invoice_date':'15-01-2026','party_name':party['name'],'kind':kind,
                    'currency':'EUR'},[{'description':'Synthetic EUR','quantity':1,'unit_price':100,'vat_rate':0}],1)
                payment_kind='customer_receipt' if kind=='sale' else 'supplier_payment'
                payload={'kind':payment_kind,'payment_date':'15-02-2026','party_id':party['id'],'currency':'EUR',
                    'amount':'100','cash_account':'531','party_account':party['account_number']}
                pid=self.db.add_payment(payload,1)
                for amount,factor in [('50',Decimal('.5')),('100',Decimal('1')),('100',Decimal('1'))]:
                    self.db.save_allocations(pid,[{'invoice_id':iid,'amount':amount}],1)
                    with self.db.connect() as c:
                        net=c.execute("""SELECT DSUM_EXACT(j.debit)-DSUM_EXACT(j.credit) FROM journal_entries e
                            JOIN journal_lines j ON j.entry_id=e.id JOIN accounts a ON a.id=j.account_id
                            WHERE e.source_type='payment_fx' AND e.source_id=? AND a.code=?""",(pid,party['account_number'])).fetchone()[0]
                    self.assertIsNotNone(net,'Allocated foreign settlement requires a realized FX entry')
                    self.assertEqual(Decimal(str(net)),Decimal(expected)*factor)
                    if amount=='50':
                        original=self.db._post_allocation_fx
                        def fail_after_fx(*args):
                            original(*args)
                            raise RuntimeError('Synthetic failure after FX write')
                        with patch.object(self.db,'_post_allocation_fx',side_effect=fail_after_fx):
                            with self.assertRaisesRegex(RuntimeError,'after FX'):
                                self.db.save_allocations(pid,[{'invoice_id':iid,'amount':'100'}],1)
                        self.assertEqual(Decimal(str(self.db.payment_allocations(pid)[0]['amount'])),Decimal('50'))
                trial=[r for r in self.db.trial_balance(account_code=party['account_number'],include_subaccounts=False)]
                self.assertEqual(sum(Decimal(str(r['closing_balance'])) for r in trial),0)
                self.assertEqual(sum(Decimal(str(r['usd_closing_balance'])) for r in trial),0)
                self.assertEqual(sum(Decimal(str(r['lbp_closing_balance'])) for r in trial),0)
                for currency in (None, 'EUR', 'USD'):
                    ledger=self.db.general_ledger(account_code=party['account_number'],currency=currency)
                    self.assertEqual(sum(Decimal(str(r['debit']))-Decimal(str(r['credit'])) for r in ledger['items']),0)
                    self.assertTrue(all(r['currency']=='EUR' for r in ledger['items']))
                fx_journal=self.db.journal(source_type='payment_fx')
                self.assertEqual(sum(Decimal(str(r['debit']))-Decimal(str(r['credit'])) for r in fx_journal),0)
                lines=ledger_reports._load_lines(self.db,{'account_from':party['account_number'],'account_to':party['account_number'],
                    'first_column':'USD','second_column':'account'})
                self.assertEqual(sum(r['signed']['USD'] for r in lines),0)
                self.assertEqual(sum(r['signed']['account'] for r in lines),0)
                with self.db.connect() as c:
                    row=c.execute('SELECT * FROM payments WHERE id=?',(pid,)).fetchone()
                    self.db._reverse_payment_entry(c,row,1,'16-02-2026')
                trial=self.db.trial_balance(account_code=party['account_number'],include_subaccounts=False)
                expected_balance=Decimal('110')*(1 if kind=='sale' else -1)
                self.assertEqual(sum(Decimal(str(r['usd_closing_balance'])) for r in trial),expected_balance)
                self.assertEqual(sum(Decimal(str(r['lbp_closing_balance'])) for r in trial),expected_balance*Decimal('89500'))
                self.assertFalse(self.db.unbalanced_entries())


if __name__=='__main__':unittest.main()
