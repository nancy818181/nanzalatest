"""2.9.106: "Customs per item" shared only by the items subject to customs, "Customs fees" by every item."""
import tempfile
import unittest
from pathlib import Path

import inventory
from database import Database


class CustomsGroupsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "books.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        # A: customs group 1, B: no customs, C: customs group 2
        self.a = inventory.save_item(self.db, {"name": "Item A", "customs_group": "Subject to customs"}, 1)
        self.b = inventory.save_item(self.db, {"name": "Item B"}, 1)
        self.c = inventory.save_item(self.db, {"name": "Item C", "customs_group": "2"}, 1)
        self.purchase = self.db.create_manual_invoice({"invoice_number": "IMP-1", "invoice_date": "10-01-2025", "party_name": "Foreign supplier", "kind": "purchases",
                                                       "currency": "USD", "status": "posted"},
            [{"description": "A", "quantity": 10, "unit_price": 100, "vat_rate": 0, "item_code": self.a["sku"]},   # 1,000
             {"description": "B", "quantity": 10, "unit_price": 50, "vat_rate": 0, "item_code": self.b["sku"]},    # 500
             {"description": "C", "quantity": 10, "unit_price": 50, "vat_rate": 0, "item_code": self.c["sku"]}], 1)  # 500

    def cost(self, item): return round(next(i["average_cost"] for i in inventory.list_items(self.db) if i["sku"] == item["sku"]), 4)

    def test_group_boxes_go_only_to_their_items(self):
        self.assertEqual(inventory.customs_group("Subject to customs"), "1"); self.assertEqual(inventory.customs_group("Yes"), "1"); self.assertEqual(inventory.customs_group("No customs"), "")
        # freight 200 and "all items" 60 by value (A 50%, B 25%, C 25%); group 1: 100 to A only; group 2: 25 to C only
        self.db.add_landed_cost(self.purchase, {"freight": "200", "customs_duties": "60", "customs_group_1": "100", "customs_group_2": "25", "import_vat": "40"}, 1)
        self.assertEqual(self.cost(self.a), 100 + (100 + 30 + 100) / 10)   # 123.0
        self.assertEqual(self.cost(self.b), 50 + (50 + 15) / 10)           # 56.5 - no customs of a group
        self.assertEqual(self.cost(self.c), 50 + (50 + 15 + 25) / 10)      # 59.0
        # the customs amounts are posted to the customs account (601800003), the books balance
        rows = self.db.trial_balance(to_date="31-12-2025")
        customs = sum(float(r["debit"]) - float(r["credit"]) for r in rows if r["code"] == "601800003")
        self.assertAlmostEqual(customs, 185.0)
        self.assertAlmostEqual(sum(float(r["debit"]) for r in rows), sum(float(r["credit"]) for r in rows), places=2)

    def test_group_without_items_is_shared_by_all(self):
        with self.db.connect() as db: db.execute("UPDATE inventory_items SET customs_group=NULL")  # nobody in group 1 any more
        self.db.add_landed_cost(self.purchase, {"customs_group_1": "200"}, 1)
        self.assertEqual(self.cost(self.a), 110.0); self.assertEqual(self.cost(self.b), 55.0); self.assertEqual(self.cost(self.c), 55.0)


if __name__ == "__main__":
    unittest.main()
