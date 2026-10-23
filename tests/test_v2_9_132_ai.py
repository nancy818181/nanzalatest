"""2.9.132 Phase 2 - AI Accountant account suggestions on the company's own chart: confidence, reason, extracted facts kept
apart from inferences, abstention, review only, nothing posted. Synthetic data only."""
import tests_setup  # noqa: F401
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import advisor
import ai_mapper
import posting_rules
from database import Database
from nanza.ai_accountant.classifier import suggest_account


class _Company(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "ai.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.user = self.db.user_for_token(self.db.login("admin", "secret12345")["token"])["id"]
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, self.user)

    def purchase(self, number, account, party="Alpha Trading SARL", status="posted", vat_use="taxable"):
        return self.db.import_invoice({"invoice_number": number, "kind": "purchase", "invoice_date": "10-03-2026", "party_name": party, "currency": "USD",
                                       "subtotal": "100", "vat": "11", "total": "111", "status": status, "expense_account": account,
                                       "vat_use": vat_use}, self.user)

    def counts(self):
        with self.db.connect() as connection:
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("journal_entries", "journal_lines", "invoices", "audit_log"))


class KeywordSuggestionsTest(_Company):
    def test_english_french_arabic_on_the_default_chart(self):
        for text, code in (("Electricity bill EDL October", "6263.4"), ("Office rent October", "6263.1"),
                           ("فاتورة كهرباء مولد", "6263.4"), ("Loyer bureau octobre", "6263.1"), ("Telephone Ogero internet", "6261.5")):
            with self.subTest(text=text):
                result = advisor.suggest(self.db, "expense", text=text)
                self.assertEqual(result["status"], "suggested")
                s = result["suggestion"]
                self.assertEqual(s["account_code"], code)
                self.assertIn(code, advisor.chart(self.db))                    # an account of THIS chart
                self.assertTrue(s["account_name"]); self.assertIn(s["level"], ("high", "medium", "low"))
                self.assertIn("not a measured accuracy", s["explanation"])
                kinds = {e["kind"] for e in s["evidence"]}
                self.assertEqual(kinds, {"extracted", "inferred"})             # read words kept apart from the inference
                self.assertTrue(result["requires_review"]); self.assertTrue(result["posts_nothing"])

    def test_mixed_language_keeps_the_original_text(self):
        text = "Facture loyer - إيجار المكتب"
        result = advisor.suggest(self.db, "expense", text=text)
        self.assertEqual(result["suggestion"]["account_code"], "6263.1")
        self.assertEqual(result["original_text"], text)
        self.assertEqual(result["languages"], ["arabic", "latin (English / French)"])

    def test_ambiguous_and_unknown_abstain(self):
        mixed = advisor.suggest(self.db, "expense", text="Water and office rent")
        self.assertTrue(mixed["abstain"]); self.assertIsNone(mixed["suggestion"])
        self.assertEqual({c["account_code"] for c in mixed["candidates"]}, {"6263.3", "6263.1"})
        unknown = advisor.suggest(self.db, "purchase", party="Never Seen Before Co", text="Invoice 005 Total 90")
        self.assertTrue(unknown["abstain"]); self.assertIn("choose the account", unknown["abstain_reason"])

    def test_threshold_is_the_companys_setting(self):
        with self.db.connect() as connection:
            connection.execute("INSERT INTO app_settings(key,value) VALUES('ai_min_confidence','0.80')")
        result = advisor.suggest(self.db, "expense", text="Office rent October")      # one keyword: 0.78
        self.assertTrue(result["abstain"]); self.assertEqual(result["threshold"], Decimal("0.80"))
        self.assertEqual(result["candidates"][0]["account_code"], "6263.1")
        self.assertIn("under the company's threshold", result["abstain_reason"])


class HistoryTest(_Company):
    def test_posted_history_only_with_tax_flag(self):
        self.purchase("A-1", "6262"); self.purchase("A-2", "6262")
        self.purchase("A-3", "6263.1", status="review")                                # not reviewed: ignored
        cancelled = self.purchase("A-4", "6263.1"); self.db.cancel_invoice(cancelled, "synthetic", self.user)   # cancelled: ignored
        result = advisor.suggest(self.db, "purchase", party="ALPHA TRADING s.a.r.l.", text="spare parts")
        s = result["suggestion"]
        self.assertEqual((s["account_code"], s["source"], s["transaction_type"]), ("6262", "posted history", "purchases"))
        self.assertEqual(s["confidence"], Decimal("0.91"))                               # 2 of 2 posted: 0.70 + 2 x 0.08 + 0.05
        self.assertEqual(s["vat_use"], "taxable"); self.assertIn("NEEDS ACCOUNTANT CONFIRMATION", s["tax_note"])

    def test_split_history_abstains_with_candidates(self):
        self.purchase("B-1", "6262"); self.purchase("B-2", "6263.1")
        result = advisor.suggest(self.db, "purchase", party="Alpha Trading SARL")
        self.assertTrue(result["abstain"]); self.assertEqual({c["account_code"] for c in result["candidates"]}, {"6262", "6263.1"})

    def test_an_account_that_is_no_longer_active_is_not_proposed(self):
        self.purchase("C-1", "6262"); self.purchase("C-2", "6262")
        with self.db.connect() as connection: connection.execute("UPDATE accounts SET active=0 WHERE code='6262'")
        result = advisor.suggest(self.db, "purchase", party="Alpha Trading SARL", text="Office rent")
        self.assertTrue(any("no longer an active posting account" in w for w in result["warnings"]))
        self.assertNotEqual((result["suggestion"] or {}).get("account_code"), "6262")

    def test_user_correction_changes_the_next_suggestion(self):
        self.purchase("D-1", "6263.1"); self.purchase("D-2", "6262"); self.purchase("D-3", "6262"); self.purchase("D-4", "6262")
        self.assertEqual(advisor.suggest(self.db, "purchase", party="Alpha Trading SARL")["suggestion"]["account_code"], "6262")


class ChecksTest(_Company):
    def test_conflicting_totals_and_duplicate_need_review(self):
        self.purchase("INV-0045", "6262", party="Beta Supplies")
        result = advisor.suggest(self.db, "purchase", party="Beta Supplies", invoice_number="INV 45", text="maintenance",
                                 subtotal="100", vat="11", total="120")
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(any("Totals do not agree" in w for w in result["warnings"]))
        self.assertEqual(result["possible_duplicate"]["invoice_number"], "INV-0045")
        self.assertEqual(result["extracted"]["total"], Decimal("120.00"))                # the figure read, unchanged

    def test_suggesting_changes_nothing(self):
        self.purchase("E-1", "6262")
        before = self.counts()
        advisor.suggest(self.db, "purchase", party="Alpha Trading SARL", text="repair", invoice_number="E-1", subtotal="1", vat="0", total="1")
        self.assertEqual(self.counts(), before)


class ExistingSuggestionPathsTest(_Company):
    def test_posting_rules_propose_accounts_of_this_chart_only(self):
        result = posting_rules.suggest(self.db, "expense", text="Electricity EDL bill")
        self.assertEqual(result["account"]["code"], "6263.4")                             # was 626340000, not in the chart

    def test_chart_name_guess_needs_a_shared_word(self):
        accounts = [f"{a['code']} - {a['name_en']}" for a in self.db.list_accounts()]
        self.assertIsNone(ai_mapper.suggest_account("Electricity bill EDL October", accounts))   # was 6515 Depreciation ...
        self.assertEqual(ai_mapper.suggest_account("Office supplies", ["601100000 - Office supplies"])["code"], "601100000")

    def test_expense_screen_suggestion_on_the_default_chart(self):
        result = suggest_account("Electricity bill EDL October", self.db.list_accounts())
        self.assertFalse(result["abstain"]); self.assertEqual(result["account_code"], "6263.4")
        self.assertTrue(result["requires_review"]); self.assertIn("Review before saving", result["explanation"])
        unknown = suggest_account("Invoice 005 Total 90", self.db.list_accounts())
        self.assertTrue(unknown["abstain"]); self.assertIn("choose the account", unknown["explanation"])


if __name__ == "__main__":
    unittest.main()
