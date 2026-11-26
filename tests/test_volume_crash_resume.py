import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from tools.plan_volume_210000 import make_plan


class VolumeCrashResumeTest(unittest.TestCase):
    def test_open_batch_and_committed_before_checkpoint_resume_without_duplicates(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);make_plan(root/'inputs',sales=4,purchases=4)
            runner=Path(__file__).resolve().parents[1]/'tools'/'run_volume_210000.py'
            args=[sys.executable,str(runner),'--inputs',str(root/'inputs'/'volume-inputs.jsonl'),
                  '--job',str(root/'job'),'--batch-size','8']
            first=subprocess.run(args+['--crash-after-save','3'],capture_output=True,text=True,timeout=90)
            self.assertEqual(first.returncode,23,first.stderr)
            database=root/'job'/'synthetic-volume-company-a-2026.db'
            with sqlite3.connect(database) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],0)
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            second=subprocess.run(args+['--crash-before-checkpoint','1'],capture_output=True,text=True,timeout=90)
            self.assertEqual(second.returncode,24,second.stderr)
            with sqlite3.connect(database) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],4)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],4)
            resumed=subprocess.run(args,capture_output=True,text=True,timeout=90)
            self.assertEqual(resumed.returncode,0,resumed.stderr)
            result=json.loads((root/'job'/'result.json').read_text())
            self.assertEqual(result['actual_counts']['sales_invoices'],4)
            self.assertEqual(result['actual_counts']['purchase_invoices'],4)
            self.assertEqual(result['actual_counts']['receipts'],4)
            self.assertEqual(result['actual_counts']['payments'],4)
            self.assertEqual(result['actual_counts']['allocations'],12)
            self.assertEqual(result['actual_counts']['journal_entries'],17)  # sixteen source documents + opening
            self.assertEqual(result['unbalanced_entries'],[])
            self.assertFalse(result['complete_210000'])
