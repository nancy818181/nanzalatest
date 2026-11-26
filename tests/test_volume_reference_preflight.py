"""Small input oracle through the same stores as the live application."""
from decimal import Decimal as D
import json
from pathlib import Path
import tempfile
import unittest
from database import Database
from tools.plan_volume_210000 import make_plan


class VolumeReferencePreflight(unittest.TestCase):
    def test_document_values_and_atomic_allocations_in_three_currencies(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);make_plan(root/'inputs',sales=48,purchases=48)
            db=Database(root/'synthetic.db',pooled=True);self.addCleanup(db.release)
            db.initialize('Synthetic-volume-preflight-2026!')
            for quarter in range(4):
                month=quarter*3+1
                for day,rate in [(15,'1.10'),(20,'1.20')]:
                    db.save_exchange_rate({'date_from':f'{day:02}-{month:02}-2026','from_currency':'EUR','to_currency':'USD','rate':rate},1)
            db.save_exchange_rate({'date_from':'01-01-2026','from_currency':'USD','to_currency':'LBP','rate':'89500'},1)
            ids={};cash_count=0
            for text in (root/'inputs'/'volume-inputs.jsonl').read_text().splitlines():
                row=json.loads(text)
                if 'invoice' in row:
                    iid=db.create_manual_invoice(row['invoice'],row['lines'],1);ids[row['reference']]=iid
                    with db.connect() as c:actual=c.execute('SELECT subtotal,vat,total FROM invoices WHERE id=?',(iid,)).fetchone()
                    for field,column in [('base','subtotal'),('vat','vat'),('total','total')]:
                        self.assertEqual(D(actual[column]),D(row['expected'][field]),(row['reference'],field))
                else:
                    party=next(p for p in db.list_parties() if p['name']==row['party_name'])
                    db.add_payment({'kind':'customer_receipt' if row['type']=='receipt' else 'supplier_payment',
                        'party_id':party['id'],'payment_number':row['reference'],'payment_date':row['date'],
                        'currency':row['currency'],'amount':row['amount'],
                        'allocations':[{'invoice_id':ids[a['invoice_reference']],'amount':a['amount']} for a in row['allocations']]},1)
                    cash_count+=1
            self.assertEqual(len(ids),96);self.assertEqual(cash_count,96)
            with db.connect() as c:
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(c.execute('SELECT COUNT(*) FROM payment_allocations').fetchone()[0],144)
                for entry in c.execute('SELECT entry_id,DSUM_EXACT(debit) debit,DSUM_EXACT(credit) credit FROM journal_lines GROUP BY entry_id'):
                    self.assertEqual(D(entry['debit']),D(entry['credit']))
