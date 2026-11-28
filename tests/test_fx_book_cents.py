"""Owner-approved2026-11-27: new foreign documents carry rounded book cents."""
import tests_setup
from pathlib import Path
from decimal import Decimal as D,ROUND_HALF_UP
from unittest import mock
import tempfile,unittest
from database import Database

class FxBookCentsTest(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(self.folder.cleanup)
  self.db=Database(Path(self.folder.name)/'synthetic.db',pooled=True);self.db.initialize('Synthetic-cents-only-2026!');self.addCleanup(self.db.release)
  for day,rate in [('01-01-2026','1.10'),('01-02-2026','1.20'),('01-03-2026','1.00')]:self.db.save_exchange_rate({'date_from':day,'from_currency':'EUR','to_currency':'USD','rate':rate},1)
  self.db.save_exchange_rate({'date_from':'01-01-2026','from_currency':'USD','to_currency':'LBP','rate':'89500'},1)
 def fixture(self,kind='sale',price='100.15',vat='0'):
  p=self.db.save_party({'name':'Synthetic '+kind,'kind':'customer' if kind=='sale' else 'supplier','currency':'EUR'},1)
  i=self.db.create_manual_invoice({'invoice_number':'CENT-'+kind,'invoice_date':'15-01-2026','party_name':p['name'],'kind':kind,'currency':'EUR'},[{'description':'Cents fixture','quantity':'1','unit_price':price,'vat_rate':vat}],1)
  return p,i
 def pay(self,p,i,amount,kind='customer_receipt',date='15-02-2026'):
  pid=self.db.add_payment({'kind':kind,'payment_date':date,'party_id':p['id'],'currency':'EUR','amount':amount,'cash_account':'531','party_account':p['account_number']},1)
  self.db.save_allocations(pid,[{'invoice_id':i,'amount':amount}],1);return pid
 def balances(self,code,date=None):
  rows=self.db.trial_balance(account_code=code,include_subaccounts=False,to_date=date)
  return tuple(sum((D(str(r[k])) for r in rows),D(0)) for k in ['closing_balance','usd_closing_balance','lbp_closing_balance'])
 def test_owner_split_receipts_close_native_USD_LBP_and_retries(self):
  p,i=self.fixture();first=self.pay(p,i,'50.08')
  self.assertEqual(self.balances(p['account_number'])[:2],(D('50.07'),D('55.08')))
  second=self.pay(p,i,'50.07',date='16-02-2026')
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))
  self.assertEqual(self.balances('775100000')[1],D('-10.01'))
  for _ in range(2):self.db.save_allocations(first,[{'invoice_id':i,'amount':'50.08'}],1)
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))
  before=self.db.aging_report('2026-02-15','sale');after=self.db.aging_report('2026-02-16','sale')
  self.assertEqual(sum(D(str(r['outstanding'])) for r in before),D('50.07'))
  self.assertEqual(sum(D(str(r['outstanding'])) for r in after),D(0))
  import ledger_reports
  rows=ledger_reports._load_lines(self.db,{'account_from':p['account_number'],'account_to':p['account_number'],'posting_status':'posted','first_column':'USD','second_column':'LBP'})
  self.assertEqual(sum(r['signed']['USD'] for r in rows),D(0));self.assertEqual(sum(r['signed']['LBP'] for r in rows),D(0))
  with self.db.connect() as c:self.db._reverse_payment_entry(c,c.execute('SELECT * FROM payments WHERE id=?',(second,)).fetchone(),1,'17-02-2026')
  self.assertEqual(self.balances(p['account_number'])[:2],(D('50.07'),D('55.08')))
  self.assertFalse(self.db.unbalanced_entries())
 def test_supplier_gain_and_loss_and_full_payment(self):
  for kind,date,account,expected in [('purchase','15-02-2026','675100000','10.01'),('sale','15-03-2026','675100000','10.02')]:
   old=self.balances(account)[1]
   p,i=self.fixture(kind);self.pay(p,i,'50.08',kind='supplier_payment' if kind=='purchase' else 'customer_receipt',date=date);self.pay(p,i,'50.07',kind='supplier_payment' if kind=='purchase' else 'customer_receipt',date=date)
   self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))
   self.assertEqual(self.balances(account)[1]-old,D(expected))
 def test_rounding_line_preserves_two_equivalent_trial_balances(self):
  p,i=self.fixture(price='.14',vat='11')
  rows=self.db.trial_balance()
  for c in ['usd','lbp']:self.assertEqual(sum(D(str(r[c+'_closing_balance'])) for r in rows),D(0))
  self.assertEqual(self.balances(p['account_number'])[1],D('.18'))
  self.assertEqual(self.balances('775100000')[1],D('-.01'))
  self.db.delete_invoice(i,1,reason='Synthetic rounding reversal')
  for r in self.db.trial_balance():
   for k in ['closing_balance','usd_closing_balance','lbp_closing_balance']:self.assertEqual(D(str(r[k])),D(0))
 def test_historical_rows_are_not_rewritten(self):
  with mock.patch.object(self.db,'_freeze_document_equivalents'):
   p,i=self.fixture()
  with self.db.connect() as c:before=[dict(r) for r in c.execute('SELECT * FROM journal_lines ORDER BY id')]
  self.db.initialize('Synthetic-cents-only-2026!')
  with self.db.connect() as c:self.assertEqual(before,[dict(r) for r in c.execute('SELECT * FROM journal_lines ORDER BY id')])

 def test_frozen_book_values_do_not_depend_on_reloading_historical_rates(self):
  p,i=self.fixture()
  with mock.patch.object(self.db,'_converted_amount',side_effect=ValueError('Unavailable old rate')):
   self.assertEqual(self.balances(p['account_number'])[1],D('110.17'))
 def test_reallocation_recalculates_connected_payments_without_duplicate_posting(self):
  p,i=self.fixture();first=self.pay(p,i,'50.08');second=self.pay(p,i,'50.07')
  for amount in ['40.00','50.08','40.00','50.08']:
   self.db.save_allocations(first,[{'invoice_id':i,'amount':amount}],1)
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))
  self.assertFalse(self.db.unbalanced_entries())
 def test_current_official_specimen_uses165_not_transposed156(self):
  import vat_return
  r=vat_return.build_vat_return(self.db,2026,1);form=vat_return.official_form(r,self.db.settings())
  boxes={str(row[0]) for row in form[1][0]['rows']}
  self.assertIn('165',boxes);self.assertNotIn('156',boxes)

 def test_split_allocation_rows_for_same_invoice_use_one_cumulative_share(self):
  p,i=self.fixture();pid=self.db.add_payment({'kind':'customer_receipt','payment_date':'15-02-2026','party_id':p['id'],'currency':'EUR','amount':'100.15','cash_account':'531','party_account':p['account_number']},1)
  self.db.save_allocations(pid,[{'invoice_id':i,'amount':'50.08'},{'invoice_id':i,'amount':'50.07'}],1)
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))
  self.assertEqual(self.balances('775100000')[1],D('-10.01'))

 def test_one_receipt_allocates_two_invoices_and_retry_is_inert(self):
  p,i=self.fixture(price='50.08');second=self.db.create_manual_invoice({'invoice_number':'CENT-SECOND','invoice_date':'15-01-2026','party_name':p['name'],'kind':'sale','currency':'EUR'},[{'description':'Second','quantity':'1','unit_price':'50.07','vat_rate':'0'}],1)
  pid=self.db.add_payment({'kind':'customer_receipt','payment_date':'15-02-2026','party_id':p['id'],'currency':'EUR','amount':'100.15','cash_account':'531','allocations':[{'invoice_id':i,'amount':'50.08'},{'invoice_id':second,'amount':'50.07'}]},1)
  with self.db.connect() as c:before=c.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0]
  self.db.save_allocations(pid,[{'invoice_id':i,'amount':'50.08'},{'invoice_id':second,'amount':'50.07'}],1)
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0],before)
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))

 def test_public_reverse_and_replace_preserves_original_entry_and_cents(self):
  p,i=self.fixture();pid=self.pay(p,i,'100.15')
  with self.db.connect() as c:
   before=[tuple(r) for r in c.execute("SELECT j.* FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id WHERE e.source_type='payment' AND e.source_id=? ORDER BY j.id",(pid,))]
  corrected=self.db.update_payment(pid,{'kind':'customer_receipt','payment_date':'15-02-2026','party_id':p['id'],'currency':'EUR','amount':'100.15','cash_account':'531','allocations':[{'invoice_id':i,'amount':'100.15'}]},1)
  self.assertNotEqual(corrected,pid)
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))
  with self.db.connect() as c:
   self.assertEqual(before,[tuple(r) for r in c.execute("SELECT j.* FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id WHERE e.source_type='payment' AND e.source_id=? ORDER BY j.id",(pid,))])
   self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_log WHERE action='reverse_and_replace' AND entity_id=?",(pid,)).fetchone()[0],1)
  self.assertFalse(self.db.unbalanced_entries())

 def test_locked_allocation_retry_leaves_records_unchanged_after_reopen(self):
  p,i=self.fixture();pid=self.pay(p,i,'100.15')
  self.db.set_books_lock('28-02-2026',1)
  with self.db.connect() as c:
   before=[tuple(r) for r in c.execute('SELECT * FROM payment_allocations')]
   count=c.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0]
  with self.assertRaises(ValueError):self.db.save_allocations(pid,[{'invoice_id':i,'amount':'50'}],1)
  self.db.release()
  with self.db.connect() as c:
   self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM payment_allocations')])
   self.assertEqual(count,c.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0])
  self.assertEqual(self.balances(p['account_number']),(D(0),D(0),D(0)))

 def test_approving_first_receipt_after_final_receipt_settles_book_cents(self):
  import approvals
  party, invoice = self.fixture()
  draft = self.db.add_payment({
      "kind": "customer_receipt", "payment_date": "15-02-2026", "party_id": party["id"],
      "currency": "EUR", "amount": "50.08",
      "allocations": [{"invoice_id": invoice, "amount": "50.08"}],
  }, 1, defer_posting=True)
  entry = approvals.entry_of(self.db, "payments", draft)
  approvals.hold(self.db, entry, 1)
  self.pay(party, invoice, "50.07", date="16-02-2026")
  self.assertEqual(self.balances(party["account_number"])[0], D("50.08"))
  with mock.patch.object(self.db, "_converted_amount", side_effect=AssertionError("Use posted values")):
   result = approvals.approve_entries(self.db, [entry], {"id": 1}, require_other=False)
  self.assertEqual(len(result["approved"]), 1)
  self.assertEqual(self.balances(party["account_number"]), (D(0), D(0), D(0)))
  self.assertEqual(self.balances("775100000")[1], D("-10.01"))
  self.assertFalse(self.db.unbalanced_entries())
