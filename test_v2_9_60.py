"""2.9.60: grouped side menu, 'Needs attention' on the Dashboard, tables that fit the window."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import desktop_layout as dl

ALL_PAGES = ["dashboard_tab", "invoices_tab", "sales_tab", "manual_tab", "import_tab", "parties_tab", "transactions_tab", "purchases_tab",
             "inventory_tab", "payroll_tab", "vat_tab", "journal_tab", "account_reports_tab", "pnl_tab", "reports_tab", "settings_tab"]


class MenuGroupTests(unittest.TestCase):
    def test_every_page_is_in_exactly_one_group(self):
        groups = dl.grouped_pages(ALL_PAGES)
        listed = [a for _g, members in groups for a in members]
        self.assertEqual(sorted(listed), sorted(ALL_PAGES))
        self.assertEqual(groups[0], ("Home", ["dashboard_tab"]))
        self.assertEqual(groups[-1][0], "Settings")

    def test_pages_without_rights_and_new_pages(self):
        groups = dict(dl.grouped_pages([p for p in ALL_PAGES if p not in ("payroll_tab", "vat_tab")] + ["new_tab"]))
        self.assertNotIn("Payroll & VAT", groups)
        self.assertEqual(groups["More"], ["new_tab"])

    def test_choice_is_kept_on_this_computer(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, mock.patch("app_runtime.data_dir", return_value=Path(folder)):
            self.assertTrue(dl.side_menu_on())
            dl.save_layout_settings(side_menu=False, folded=["Inventory"])
            self.assertEqual(dl.layout_settings(), {"side_menu": False, "folded": ["Inventory"], "hidden_columns": {}})


class AttentionTests(unittest.TestCase):
    def app(self, alerts=None, unbalanced=(), backups=None, role="admin"):
        client = SimpleNamespace(document_alerts=lambda days: alerts or {"items": []}, unbalanced_entries=lambda: list(unbalanced),
                                 backups=lambda: backups if backups is not None else [])
        return SimpleNamespace(client=client, current_user={"role": role}, invoices_tab=object(), select_main_tab=lambda p: None,
                               show_document_alerts=lambda: None, check_unbalanced_entries=lambda: None, create_backup=lambda: None)

    def test_problems_are_listed(self):
        old = (datetime.now() - timedelta(days=5)).isoformat()
        items = dl.attention_items(self.app({"items": [1], "expired": 1, "expiring": 2}, [{"entry_number": "JV-1"}], [{"modified": old}]),
                                   [{"overdue": 2}, {"overdue": 1}])
        texts = [text for _l, text, *_r in items]
        self.assertTrue(texts[0].startswith("3 overdue invoice"))
        self.assertIn("1 legal document(s) expired, 2 expiring in 30 days", texts)
        self.assertIn("1 journal entry is not balanced", texts)
        self.assertEqual(items[-1][0], "amber")  # backup 5 days old

    def test_all_good(self):
        items = dl.attention_items(self.app(backups=[{"modified": datetime.now().isoformat()}]), [{"overdue": 0}])
        self.assertEqual([level for level, *_r in items], ["green", "green"])
        self.assertNotIn("Back up now", [i[2] for i in dl.attention_items(self.app(role="viewer"), [])])

    def test_a_failing_service_does_not_stop_the_dashboard(self):
        def boom(*_a): raise RuntimeError("offline")
        app = self.app(); app.client = SimpleNamespace(document_alerts=boom, unbalanced_entries=boom, backups=boom)
        self.assertEqual(dl.attention_items(app, [])[0][0], "green")


class SideMenuWidgetTests(unittest.TestCase):
    def test_buttons_follow_page_order_and_groups_fold(self):
        import tkinter as tk
        try: root = tk.Tk()
        except tk.TclError: self.skipTest("no display")
        self.addCleanup(root.destroy)
        pages = [tk.Frame(root) for _ in ALL_PAGES]; names = [a.replace("_tab", "").title() for a in ALL_PAGES]
        app = SimpleNamespace(select_main_tab=lambda p: setattr(app, "opened", p))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, mock.patch("app_runtime.data_dir", return_value=Path(folder)):
            holder = tk.Frame(root); holder.pack(fill="both", expand=True)
            buttons = dl.build_side_menu(app, holder, ALL_PAGES, pages, names); root.update()
            self.assertEqual([b.cget("text") for b in buttons], names)
            buttons[ALL_PAGES.index("journal_tab")].invoke()
            self.assertIs(app.opened, pages[ALL_PAGES.index("journal_tab")])
            body, header = app.side_menu_groups["Accounting"]
            app.toggle_menu_group("Accounting"); root.update()
            self.assertFalse(body.winfo_manager())
            self.assertEqual(dl.layout_settings()["folded"], ["Accounting"])
            self.assertTrue(dl.colour_menu_button(buttons[0], True)); self.assertEqual(buttons[0].cget("bg"), dl.GOLD)


if __name__ == "__main__":
    unittest.main()
