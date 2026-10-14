"""2.9.86 (owner): uploading an invoice - an item that does not exist is created and the user is told which items are
new; an item with 90% or more of the same name gives a warning and the user decides (use it or create a new one)."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_stage3_common as common
import inventory
from database import Database


class _Client:
    def __init__(self, db): self.db = db
    def find_or_create_item(self, name, unit="unit", sku=None, supplier_id=None): return inventory.find_or_create_item(self.db, name, unit, sku, 1, supplier_id)
    def similar_items(self, name): return inventory.similar_items(self.db, name)


class NewItemsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "b.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.existing = inventory.save_item(self.db, {"name": "HPL Panel 4mm White", "unit": "sheet"}, 1)

    def test_created_flag_and_notice(self):
        screen = types.SimpleNamespace(client=_Client(self.db))
        same = common.resolve_item(screen, "hpl panel - 4 MM white", "sheet")
        new = common.resolve_item(screen, "Cashews Raw", "1KG")
        self.assertEqual(same["id"], self.existing["id"]); self.assertNotIn("created", same)
        self.assertTrue(new["created"])
        with patch("desktop_stage3_common.messagebox.showinfo") as info:
            listed = common.notify_new_items(screen, "Purchase PDF")
        self.assertEqual([i["name"] for i in listed], ["Cashews Raw"])
        self.assertIn("1 new item(s) did not exist", info.call_args.args[1])
        with patch("desktop_stage3_common.messagebox.showinfo") as info:
            self.assertEqual(common.notify_new_items(screen), []); info.assert_not_called()  # told once

    def test_warning_only_from_90_percent(self):
        class Window(common.tk.Misc):  # a screen: the similarity check runs
            def __init__(self, client): self.client = client
        screen = Window(_Client(self.db))
        with patch("desktop_stage3_common.choose_similar_item", return_value=None) as ask:
            common.resolve_item(screen, "HPL Panel 4mm Whit", "sheet")  # 97% alike: warning, user creates a new item
            self.assertEqual(ask.call_count, 1)
            common.resolve_item(screen, "HPL Board 9mm Black", "sheet")  # far below 90%: created without a question
            self.assertEqual(ask.call_count, 1)
        self.assertEqual(sorted(i["name"] for i in screen._new_items), ["HPL Board 9mm Black", "HPL Panel 4mm Whit"])
        with patch("desktop_stage3_common.choose_similar_item", return_value=self.existing) as ask:
            chosen = common.resolve_item(screen, "HPL Panel 4mm Wite", "sheet")
        self.assertEqual(chosen["id"], self.existing["id"])


if __name__ == "__main__":
    unittest.main()
