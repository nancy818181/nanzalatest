"""2.9.101: upgrade of older files, tables that show their columns in full."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path



# 2.9.103: the hidden owner account tested here was replaced by a signed licence - see test_v2_9_103.py


class UpgradeFingerprintTest(unittest.TestCase):
    def test_new_tables_change_the_upgrade_fingerprint(self):
        import database, approvals
        source = database._schema_fingerprint.__code__.co_names + database._schema_fingerprint.__code__.co_consts
        self.assertIn("approvals", source); self.assertIn("audit_chain", source)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = database.Database(str(Path(folder) / "u.db")); db.initialize_if_needed("secret12345")
            with db.connect() as connection:
                connection.execute("DROP TABLE held_journal_lines")
                connection.execute("UPDATE app_settings SET value='old' WHERE key='startup_schema_version'")
            db2 = database.Database(str(Path(folder) / "u.db")); db2.initialize_if_needed("secret12345")
            self.assertEqual(approvals.pending(db2), [])


class ColumnFitTest(unittest.TestCase):
    def test_columns_show_title_and_fill_width(self):
        import tkinter as tk
        from tkinter import ttk
        import desktop_common  # noqa: F401 - installs the column fit
        try: root = tk.Tk()
        except tk.TclError: self.skipTest("no display")
        try:
            root.geometry("900x300")
            tree = ttk.Treeview(root, columns=("a", "b", "c"), show="headings"); tree.pack(fill="both", expand=True)
            tree.heading("a", text="A very long column title here"); tree.column("a", width=40)
            tree.heading("b", text="B"); tree.column("b", width=60)
            tree.heading("c", text="Hidden"); tree.column("c", width=0, minwidth=0, stretch=False)
            tree.insert("", "end", values=("x", "10-10-2026 long value", "z"))
            for _ in range(5): root.update(); time.sleep(0.05)
            from tkinter import font as tkfont
            self.assertGreaterEqual(tree.column("a", "width"), 150)
            self.assertEqual(tree.column("c", "width"), 0)
            self.assertGreater(tree.column("a", "width") + tree.column("b", "width"), 800)  # fills the table
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()


class NewItemDetailsTest(unittest.TestCase):
    def test_ask_settings_and_set_details(self):
        import inventory
        from database import Database
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "i.db"); db.initialize("secret12345")
            self.assertFalse(inventory.settings(db)["ask_brand"])
            inventory.save_settings(db, {"currency": "USD", "method": "average", "ask_category": True, "ask_brand": True}, 1)
            s = inventory.settings(db); self.assertTrue(s["ask_category"] and s["ask_brand"]); self.assertFalse(s["ask_subcategory"])
            item = inventory.save_item(db, {"name": "Steel bolt M8", "unit": "unit"}, 1) if hasattr(inventory, "save_item") else None
            item_id = item["id"] if isinstance(item, dict) else int(item)
            inventory.set_item_details(db, [{"id": item_id, "category": "Hardware", "brand": "Bosch"}], 1)
            with db.connect() as c: row = c.execute("SELECT category,brand FROM inventory_items WHERE id=?", (item_id,)).fetchone()
            self.assertEqual((row["category"], row["brand"]), ("Hardware", "Bosch"))
            self.assertIn("Hardware", [x["name"] for x in inventory.list_categories(db)["categories"]])
            self.assertIn("Bosch", inventory.brands(db))
