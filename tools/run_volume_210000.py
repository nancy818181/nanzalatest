"""Isolated, resumable workload using normal document/payment/FX stores.

No direct SQL inserts, disabled constraints, or bypassed posting validations.
The input plan supplies the independent monetary oracle.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import time
from decimal import Decimal as D


def run(inputs, job, batch_size=200, limit=None, crash_after_save=None, crash_before_checkpoint=None):
    inputs, job = Path(inputs).resolve(), Path(job).resolve()
    digest=hashlib.sha256()
    with inputs.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    fingerprint=digest.hexdigest()
    job.mkdir(parents=True,exist_ok=True)
    marker=job/'synthetic-volume-marker.json';database=job/'synthetic-volume-company-a-2026.db'
    if marker.exists():
        if json.loads(marker.read_text())['input_sha256']!=fingerprint: raise ValueError('Inputs changed; use a new isolated job')
    else:
        if database.exists(): raise ValueError('Refusing an existing database without a matching synthetic-job marker')
        marker.write_text(json.dumps({'purpose':'isolated synthetic workload only','input_sha256':fingerprint}),encoding='utf-8')
    os.environ['SABER_DATA_DIR']=str(job/'runtime')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import nanza_paths  # noqa: F401
    from database import Database
    fresh=not database.exists()
    db=Database(database,pooled=True)
    if fresh: db.initialize('Synthetic-volume-only-2026!')
    else: db.initialize_if_needed('Synthetic-volume-only-2026!')
    started=time.perf_counter();made=reused=processed=batches=0
    try:
        if fresh:
            db.save_settings({'company_name':'SYNTHETIC VOLUME A 2026','base_currency':'USD'},1)
            for quarter in range(4):
                month=quarter*3+1
                for day,rate in [(15,'1.10'),(20,'1.20')]:
                    db.save_exchange_rate({'date_from':f'{day:02}-{month:02}-2026','from_currency':'EUR','to_currency':'USD','rate':rate},1)
            db.save_exchange_rate({'date_from':'01-01-2026','from_currency':'USD','to_currency':'LBP','rate':'89500'},1)
            db.save_journal_voucher({'entry_number':'VOLUME-OPEN','entry_date':'01-01-2026','currency':'USD','voucher_type':'04'},
                [{'account_code':'531','debit':'1000000'},{'account_code':'101','credit':'1000000'}],1)
        with db.connect() as c:
            ids={r['invoice_number']:r['id'] for r in c.execute("SELECT id,invoice_number FROM invoices WHERE invoice_number LIKE 'VOL-%'")}
            payments={r['payment_number']:dict(r) for r in c.execute("SELECT * FROM payments WHERE payment_number LIKE 'VOL-%'")}
        parties={p['name']:p for p in db.list_parties()}
        with inputs.open('rb') as stream:
            records=(json.loads(line) for line in stream)
            if limit is not None:records=itertools.islice(records,limit)
            while batch:=list(itertools.islice(records,batch_size)):
                with db.connect() as c:
                    for record in batch:
                        reference=record['reference']
                        if 'invoice' in record:
                            if reference in ids: iid=ids[reference];reused+=1
                            else:
                                iid=db.create_manual_invoice(record['invoice'],record['lines'],1);ids[reference]=iid;made+=1
                            actual=c.execute('SELECT subtotal,vat,total FROM invoices WHERE id=?',(iid,)).fetchone()
                            for oracle,column in [('base','subtotal'),('vat','vat'),('total','total')]:
                                if D(actual[column])!=D(record['expected'][oracle]):
                                    raise AssertionError((reference,column,record['expected'][oracle],actual[column]))
                        else:
                            party=parties.get(record['party_name'])
                            if party is None:
                                party=next(p for p in db.list_parties() if p['name']==record['party_name']);parties[party['name']]=party
                            allocations=[{'invoice_id':ids[a['invoice_reference']],'amount':a['amount']} for a in record['allocations']]
                            if reference in payments:
                                pay=payments[reference]
                                if D(pay['amount'])!=D(record['amount']) or pay['currency']!=record['currency'] or pay['party_id']!=party['id']:
                                    raise AssertionError(('Existing payment differs from input',reference))
                                db.save_allocations(pay['id'],allocations,1);reused+=1
                            else:
                                pid=db.add_payment({'kind':'customer_receipt' if record['type']=='receipt' else 'supplier_payment',
                                    'party_id':party['id'],'payment_number':reference,'payment_date':record['date'],
                                    'currency':record['currency'],'amount':record['amount'],'cash_account':'531','allocations':allocations},1)
                                payments[reference]={'id':pid,'amount':record['amount'],'currency':record['currency'],'party_id':party['id']};made+=1
                        processed+=1
                        if processed==crash_after_save: os._exit(23)  # kill our own synthetic worker inside the open batch
                batches+=1
                if batches==crash_before_checkpoint: os._exit(24)  # committed documents; checkpoint deliberately absent
                progress={'processed_input_records':processed,'new_documents_this_process':made,'reused_documents_this_process':reused,
                    'elapsed_seconds':round(time.perf_counter()-started,3),'last_committed_batch':batches,'input_sha256':fingerprint}
                temporary=job/'progress.json.tmp';temporary.write_text(json.dumps(progress,indent=2),encoding='utf-8')
                temporary.replace(job/'progress.json')
                print(json.dumps(progress),flush=True)
        with db.connect() as c:
            integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
            counts={
                'sales_invoices':c.execute("SELECT COUNT(*) FROM invoices WHERE kind='sale' AND invoice_number LIKE 'VOL-S-%'").fetchone()[0],
                'purchase_invoices':c.execute("SELECT COUNT(*) FROM invoices WHERE kind='purchase' AND invoice_number LIKE 'VOL-P-%'").fetchone()[0],
                'receipts':c.execute("SELECT COUNT(*) FROM payments WHERE kind='customer_receipt' AND payment_number LIKE 'VOL-R-%'").fetchone()[0],
                'payments':c.execute("SELECT COUNT(*) FROM payments WHERE kind='supplier_payment' AND payment_number LIKE 'VOL-D-%'").fetchone()[0],
                'item_lines':c.execute('SELECT COUNT(*) FROM invoice_items').fetchone()[0],
                'allocations':c.execute('SELECT COUNT(*) FROM payment_allocations').fetchone()[0],
                'journal_entries':c.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0],
                'journal_lines':c.execute('SELECT COUNT(*) FROM journal_lines').fetchone()[0],
            }
            unbalanced=[]
            for row in c.execute('SELECT entry_id,DSUM_EXACT(debit) debit,DSUM_EXACT(credit) credit FROM journal_lines GROUP BY entry_id'):
                if D(row['debit'])!=D(row['credit']):unbalanced.append(row['entry_id'])
        summary={'actual_counts':counts,'integrity_check':integrity,'unbalanced_entries':unbalanced,'processed_input_records':processed,
            'input_sha256':fingerprint,'elapsed_seconds':round(time.perf_counter()-started,3),'complete_210000':processed==210000}
        (job/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary),flush=True)
        if integrity!='ok' or unbalanced:raise AssertionError(summary)
        return summary
    finally:db.release()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',required=True,type=Path);parser.add_argument('--job',required=True,type=Path)
    parser.add_argument('--batch-size',type=int,default=200);parser.add_argument('--limit',type=int)
    parser.add_argument('--crash-after-save',type=int);parser.add_argument('--crash-before-checkpoint',type=int)
    args=parser.parse_args()
    if args.batch_size<1:parser.error('batch-size must be positive')
    run(args.inputs,args.job,args.batch_size,args.limit,args.crash_after_save,args.crash_before_checkpoint)
