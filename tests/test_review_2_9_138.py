"""Review of 2.9.138 (26-10-2026): regressions found during the code review, each shown failing before its fix.

1. Arabic screens: labels added or renamed in 2.9.138 had no Arabic text (shown in English in RTL mode).
2. NSSF form summary on screen: contributions were rounded with float + Python round() (half to even), so a
   .5 LBP result disagreed with the Excel form, whose ROUND() rounds half away from zero.
3. CI annotations: a failure inside self.subTest() was not annotated, so a Windows failure in a subTest left
   no test name in the check results (the job logs cannot always be downloaded).
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ArabicLabelsOf2_9_138Test(unittest.TestCase):
    def test_new_purchase_and_sales_labels_have_arabic(self):
        import arabic_ui
        for text in ("Paid from A/C", "Department and Project", "Find purchase"):
            with self.subTest(text=text):
                self.assertTrue(arabic_ui.has_arabic(arabic_ui.translate(text)), text)


class NssfSummaryRoundingTest(unittest.TestCase):
    def test_screen_summary_rounds_half_up_like_the_excel_round(self):
        from cnss_forms import summary_rows
        data = {"period_text": "09-2026",
                "sick": {"wages": "1000100", "rate": "0.085", "count": 1},   # 85,008.5 -> 85,009 (Excel ROUND)
                "eos": {"wages": "1500050", "rate": "0.11", "count": 1},     # 165,005.5 -> 165,006
                "family": {"wages": "0", "rate": "0.06", "count": 0},
                "allowance": "0"}
        rows = dict(summary_rows("cnss_contributions_monthly_quarterly", data))
        sick = next(value for label, value in rows.items() if label.startswith("Sickness"))
        self.assertTrue(sick.endswith("= 85,009"), sick)
        self.assertEqual(rows["Total contributions"], "250,015")
        self.assertEqual(rows["Net due to the NSSF"], "250,015")


class WorkbenchDuplicateLeavesVoidOutTest(unittest.TestCase):
    """F1 (owner decision 25-10-2026): duplicate-number checks leave void invoices out, as the save-time check does.
    The workbench check (GET /api/workbench/duplicates) still counted them."""

    def test_void_invoice_is_not_reported_as_a_duplicate(self):
        import tests_setup  # noqa: F401
        from database import Database
        from nanza_delivery import ai_accountant
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "company.db"); db.initialize("Synthetic-Only-2026!")
            try:
                user = db.user_for_token(db.login("admin", "Synthetic-Only-2026!")["token"])["id"]
                invoice_id = db.import_invoice({"invoice_number": "S-DUP-1", "kind": "sale", "invoice_date": "10-02-2026",
                    "party_name": "Synthetic customer", "currency": "USD", "subtotal": "100", "vat": "11", "total": "111",
                    "status": "posted"}, user)
                self.assertEqual(len(ai_accountant.detect_duplicate("S-DUP-1", "111", "10-02-2026", db)), 1)
                db.mark_invoice_deleted(invoice_id, user, reason="synthetic correction", role="admin", void_date="2026-02-11")
                self.assertEqual(ai_accountant.detect_duplicate("S-DUP-1", "111", "10-02-2026", db), [])
            finally:
                db.release()


class CiSubTestAnnotationTest(unittest.TestCase):
    def test_a_failing_subtest_is_annotated(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "probe_tests"; package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "test_000_ci_annotations.py").write_text((ROOT / "tests" / "test_000_ci_annotations.py").read_text(encoding="utf-8"),
                                                                 encoding="utf-8")
            (package / "test_probe.py").write_text(textwrap.dedent("""
                import unittest
                class Probe(unittest.TestCase):
                    def test_sub(self):
                        with self.subTest(page="Purchase Invoice"):
                            self.assertEqual(1, 2)
                """), encoding="utf-8")
            env = dict(os.environ, GITHUB_ACTIONS="true")
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "probe_tests", "-t", ".", "-p", "test_*.py"],
                                    cwd=folder, env=env, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(result.returncode, 0)
        annotations = [line for line in result.stdout.splitlines() if line.startswith("::error ")]
        self.assertTrue(annotations, result.stdout + result.stderr)
        self.assertIn("probe_tests.test_probe.Probe.test_sub", annotations[0])
        self.assertIn("Purchase Invoice", annotations[0])


if __name__ == "__main__":
    unittest.main()
