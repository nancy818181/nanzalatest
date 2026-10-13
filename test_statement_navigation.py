"""Statement account range defaults and keyboard navigation."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from desktop_brains import BrainsScreensMixin


class Value:
    def __init__(self, value=""):
        self.value=value

    def get(self):
        return self.value

    def set(self, value):
        self.value=value


class StatementNavigationTests(unittest.TestCase):
    def test_known_start_account_fills_second_row_without_overwriting_custom_range(self):
        app=BrainsScreensMixin()
        app._all_accounts={"6011":"Expenses","601100001":"Utilities","601100002":"Rent"}
        v={"account_from":Value(""),"account_to":Value(""),"_auto_account_to":None}

        v["account_from"].set("601100001")
        app.statement_account_from_changed(v)
        self.assertEqual(v["account_to"].get(),"601100001")
        v["account_from"].set("601100002 - Rent")
        app.statement_account_from_changed(v)
        self.assertEqual(v["account_to"].get(),"601100002")

        v["account_to"].set("6011")
        v["account_from"].set("601100001")
        app.statement_account_from_changed(v)
        self.assertEqual(v["account_to"].get(),"6011")
        v["account_to"].set("")
        app.statement_account_from_changed(v)
        self.assertEqual(v["account_to"].get(),"601100001")

    def test_partial_or_unknown_account_does_not_fill_second_row(self):
        app=BrainsScreensMixin()
        app._all_accounts={"601100001":"Utilities"}
        v={"account_from":Value("6011000"),"account_to":Value(""),"_auto_account_to":None}
        app.statement_account_from_changed(v)
        self.assertEqual(v["account_to"].get(),"")

    def test_escape_steps_back_one_level_and_keeps_the_open_tabs(self):
        # 2.9.47 (owner request): Escape no longer jumps to the dashboard. In the statement / trial balance it goes
        # back one level (drilled statement -> its trial balance, report -> Options) and closes nothing.
        app=BrainsScreensMixin()
        notebook=Mock(); notebook.tabs.return_value=("options","tb","st")
        state={"notebook":notebook,"options_page":"options","parents":{"st":"tb"}}
        app.statement_tab=SimpleNamespace(master=None); app.trial_tab=SimpleNamespace(master=None)
        app.statement_state=None; app.trial_state=state; app.show_tab_window=Mock()
        inside=SimpleNamespace(widget=SimpleNamespace(master=SimpleNamespace(master=app.trial_tab)))
        notebook.select.return_value="st"
        self.assertEqual(app.statement_escape(inside),"break"); notebook.select.assert_called_with("tb")
        notebook.select.reset_mock(); notebook.select.return_value="tb"
        self.assertEqual(app.statement_escape(inside),"break"); notebook.select.assert_called_with("options")
        notebook.forget.assert_not_called(); app.show_tab_window.assert_not_called()
        app._report_return=None
        self.assertIsNone(app.statement_escape(SimpleNamespace(widget=SimpleNamespace(master=None))))

    def test_escape_on_an_editing_screen_returns_to_the_report(self):
        app=BrainsScreensMixin()
        app.statement_tab=SimpleNamespace(master=Mock()); app.trial_tab=SimpleNamespace(master=Mock())
        app.statement_state=app.trial_state=None
        app.account_reports_tab="reports"; app.go_to_main_tab=Mock(); app.run_balance_report=Mock()
        state={"statement":True,"result":{"title":"Statement"}}
        app._report_return=state
        self.assertEqual(app.statement_escape(SimpleNamespace(widget=SimpleNamespace(master=None))),"break")
        app.go_to_main_tab.assert_called_once_with("reports"); app.statement_tab.master.select.assert_called_once_with(app.statement_tab)
        app.run_balance_report.assert_called_once_with(state,refresh=True); self.assertIsNone(app._report_return)


if __name__ == "__main__":
    unittest.main()