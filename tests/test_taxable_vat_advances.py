"""Owner policy: advance100+11 in Q1, final300+33 less11 in Q2."""
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest
from database import Database
import vat_return


class TaxableAdvanceTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.db=Database(Path(self.folder.name)/'company-2026.db',pooled=True)
        self.db.initialize('Synthetic-advance-only-2026!');self.addCleanup(self.db.release)
        self.party=self.db.save_party({'name':'Synthetic taxable advance','kind':'customer','currency':'USD'},1)

    def receipt(self, taxable=True):
        return self.db.add_payment({'kind':'customer_receipt','payment_date':'20-03-2026','party_id':self.party['id'],
            'currency':'USD','amount':'111','cash_account':'531','taxable_advance':taxable},1)

    def invoice(self):
        return self.db.create_manual_invoice({'invoice_date':'10-04-2026','party_name':self.party['name'],
            'kind':'sale','currency':'USD'},[{'description':'Final service','quantity':'1','unit_price':'300','vat_rate':'11'}],1)

    def output(self,quarter):
        r=vat_return.build_vat_return(self.db,2026,quarter)
        return D(str(r['per_currency'].get('USD',{}).get('total_output',{}).get('vat',0)))

    def test_full_application_and_repeat_have_owner_quarter_totals(self):
        payment=self.receipt();invoice=self.invoice()
        self.assertEqual(self.output(1),D(11))
        for _ in range(2): self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':'111'}],1)
        self.assertEqual(self.output(2),D(22))
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_vat_advance_applications').fetchone()[0],1)
            for row in c.execute('SELECT entry_id,DSUM_EXACT(debit) d,DSUM_EXACT(credit) c FROM journal_lines GROUP BY entry_id'):
                self.assertEqual(D(row['d']),D(row['c']))

    def test_partial_then_remaining_and_undo_preserve_traceable_entries(self):
        payment=self.receipt();invoice=self.invoice()
        for amount,vat in [('55.50','27.50'),('111','22'),('55.50','27.50'),('0','33')]:
            self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':amount}],1)
            self.assertEqual(self.output(2),D(vat))
        self.assertEqual(self.output(1),D(11))
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_vat_advance_applications').fetchone()[0],4)

    def test_ordinary_receipt_is_not_reinterpreted(self):
        self.receipt(False)
        self.assertEqual(self.output(1),D(0))
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_vat_advances').fetchone()[0],0)

    def test_overallocation_rolls_back_all_changes_after_reopen(self):
        payment=self.receipt();invoice=self.invoice()
        with self.assertRaises(ValueError):self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':'112'}],1)
        self.db.release()
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_allocations').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_vat_advance_applications').fetchone()[0],0)
        self.assertEqual(self.output(1),D(11));self.assertEqual(self.output(2),D(33))

    def test_historical_aging_and_vat_ledger_match_after_application(self):
        import business_reports
        payment=self.receipt();invoice=self.invoice()
        self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':'111'}],1)
        for day,expected in [('31-03-2026','-100'),('30-06-2026','222')]:
            r=business_reports.ageing(self.db,{'date_to':day,'basis':'USD','fifo':False})
            summary=next(s for s in r['sections'] if s['heading']=='Ageing summary')
            actual=next(row[1] for row in summary['rows'] if row[0]=='NET BALANCE')
            self.assertEqual(D(str(actual)),D(expected))
            self.assertEqual(sum((D(str(row['outstanding'])) for row in self.db.aging_report(day,kind='sale',currency='USD')),D(0)),D(expected))
        for q in (1,2):
            result=vat_return.build_vat_return(self.db,2026,q)
            checked=vat_return.ledger_check(self.db,result)
            self.assertTrue(checked['agreed'],checked)

    def test_admin_void_reverses_recognition_and_application_without_erasing_history(self):
        payment=self.receipt();invoice=self.invoice()
        self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':'111'}],1)
        with self.assertRaises(PermissionError):self.db.delete_payment(payment,1,'Test denial',role='accountant')
        self.db.delete_payment(payment,1,'Test approved reversal',role='admin')
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_vat_advances').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM journal_entries WHERE reversal_of IS NOT NULL').fetchone()[0],2)
        self.assertEqual(self.output(1)+self.output(2)+self.output(4),D(33))
        import business_reports
        for day,wanted in [('31-03-2026','-100'),('30-06-2026','222'),('31-12-2026','333')]:
            report=business_reports.ageing(self.db,{'date_to':day,'basis':'USD','fifo':False})
            summary=next(s for s in report['sections'] if s['heading']=='Ageing summary')
            self.assertEqual(D(str(next(row[1] for row in summary['rows'] if row[0]=='NET BALANCE'))),D(wanted))

    def test_box_110_separates_base_from_tax_and_final_box_100_is_net(self):
        self.db.save_exchange_rate({'date_from':'01-01-2026','from_currency':'USD','to_currency':'LBP','rate':'89500'},1)
        payment=self.receipt();invoice=self.invoice()
        self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':'111'}],1)
        for quarter,box,base,tax in [(1,'110','8950000','984500'),(2,'100','17900000','1969000')]:
            form=vat_return.official_form(vat_return.build_vat_return(self.db,2026,quarter),{})
            row=next(row for section in form[1] for row in section.get('rows',[]) if str(row[0])==box)
            self.assertEqual(D(str(row[3])),D(base));self.assertEqual(D(str(row[4])),D(tax))

    def test_draft_is_excluded_and_failed_vat_lock_application_is_atomic(self):
        pid=self.db.add_payment({'kind':'customer_receipt','payment_date':'20-03-2026','party_id':self.party['id'],
            'currency':'USD','amount':'111','taxable_advance':True},1,defer_posting=True)
        self.assertEqual(self.output(1),D(0))
        self.db.delete_payment(pid,1)
        payment=self.receipt();invoice=self.invoice()
        vat_return.save_return(self.db,2026,2,1)
        with self.assertRaises(ValueError):self.db.save_allocations(payment,[{'invoice_id':invoice,'amount':'111'}],1)
        self.db.release()
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_allocations').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_vat_advance_applications').fetchone()[0],0)

    def test_edit_allocation_keeps_receipt_identity_and_rejects_financial_rewrite(self):
        payment=self.receipt();invoice=self.invoice()
        self.assertEqual(self.db.update_payment(payment,{'allocations':[{'invoice_id':invoice,'amount':'111'}]},1),payment)
        self.assertEqual(self.output(1),D(11));self.assertEqual(self.output(2),D(22))
        with self.assertRaises(ValueError):self.db.update_payment(payment,{'amount':'112'},1)
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],1)
            self.assertIsNone(c.execute('SELECT voided_at FROM payments WHERE id=?',(payment,)).fetchone()[0])
