"""2.9.65: production - recipes (bills of materials), production orders, cost of the finished product."""
import tempfile
import unittest

import inventory
import production
from test_final_features import new_db


class ProductionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.db, self.user = new_db(self.folder.name)
        for sku, name, unit in (("SHEET", "HPL sheet", "m2"), ("GLUE", "Glue", "kg"), ("PANEL", "Panel", "piece")):
            inventory.save_item(self.db, {"sku": sku, "name": name, "unit": unit}, self.user)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "01-02-2025", "warehouse_id": "MAIN"},
                                [{"sku": "SHEET", "quantity": 100, "unit_cost": 10}, {"sku": "GLUE", "quantity": 50, "unit_cost": 4}], self.user)
        production.save_bom(self.db, {"sku": "PANEL", "output_qty": 10, "overhead_per_unit": 2, "lines": [{"sku": "SHEET", "quantity": 20}, {"sku": "GLUE", "quantity": 4}]}, self.user)

    def tearDown(self): self.folder.cleanup()

    def stock(self):
        return {i["sku"]: (i["quantity"], round(i["average_cost"], 4)) for i in inventory.list_items(self.db)}

    def make(self, quantity, lines=None, date="10-02-2025", extra=None):
        plan = production.plan(self.db, "PANEL", quantity, "MAIN", date)
        lines = lines or [{"sku": l["sku"], "quantity": l["quantity"]} for l in plan["lines"]]
        return production.save_order(self.db, {"doc_date": date, "sku": "PANEL", "quantity": quantity, "warehouse_id": "MAIN",
                                               "extra_cost": plan["extra_cost"] if extra is None else extra}, lines, self.user)

    def test_recipe_scaled_and_cost_of_the_product(self):
        plan = production.plan(self.db, "PANEL", 25, "MAIN")
        self.assertEqual([(l["sku"], l["quantity"]) for l in plan["lines"]], [("SHEET", 50.0), ("GLUE", 10.0)]); self.assertEqual(plan["extra_cost"], 50.0)
        order = self.make(25)
        self.assertEqual(order["number"], "PRD-2025-000001")
        self.assertEqual((order["material_cost"], order["extra_cost"], order["total_cost"]), (540.0, 50.0, 590.0))
        self.assertEqual(self.stock(), {"SHEET": (50.0, 10.0), "GLUE": (40.0, 4.0), "PANEL": (25.0, 23.6)})

    def test_special_order_changes_only_that_order(self):
        order = self.make(5, [{"sku": "SHEET", "quantity": 12}, {"sku": "GLUE", "quantity": 1}], extra=0)
        self.assertEqual(order["total_cost"], 124.0)
        self.assertEqual([l["quantity"] for l in production.get_bom(self.db, "PANEL")["lines"]], [20.0, 4.0])

    def test_cost_follows_a_purchase_entered_later(self):
        order = self.make(25)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "05-02-2025", "warehouse_id": "MAIN"}, [{"sku": "SHEET", "quantity": 100, "unit_cost": 4}], self.user)
        self.assertEqual(production.get_order(self.db, order["id"])["total_cost"], 440.0)  # sheet average 7: 350 + 40 + 50
        self.assertEqual(self.stock()["PANEL"], (25.0, 17.6))

    def test_fifo(self):
        inventory.save_settings(self.db, {"method": "fifo", "currency": "USD"}, self.user)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "03-02-2025", "warehouse_id": "MAIN"}, [{"sku": "SHEET", "quantity": 100, "unit_cost": 20}], self.user)
        order = self.make(60, extra=0)  # 120 m2: 100 at 10 + 20 at 20, glue 24 at 4
        self.assertEqual(order["total_cost"], 1496.0)

    def test_not_enough_material_asks_first(self):
        with self.assertRaises(inventory.NegativeStock):
            self.make(5, [{"sku": "SHEET", "quantity": 999}])
        with inventory.negative_stock_allowed():
            self.make(5, [{"sku": "SHEET", "quantity": 999}], extra=0)
        self.assertEqual(self.stock()["SHEET"][0], -899.0)

    def test_delete_order_puts_materials_back(self):
        order = self.make(25)
        inventory.delete_document(self.db, order["id"], self.user)
        self.assertEqual(self.stock(), {"SHEET": (100.0, 10.0), "GLUE": (50.0, 4.0), "PANEL": (0.0, 0.0)})

    def test_product_already_sold_cannot_be_unmade(self):
        order = self.make(25)
        inventory.save_document(self.db, {"doc_type": "issue", "doc_date": "20-02-2025", "warehouse_id": "MAIN"}, [{"sku": "PANEL", "quantity": 20}], self.user)
        with self.assertRaisesRegex(ValueError, "negative"): inventory.delete_document(self.db, order["id"], self.user)

    def test_edit_order(self):
        order = self.make(25)
        edited = production.save_order(self.db, {"doc_date": "10-02-2025", "sku": "PANEL", "quantity": 10, "warehouse_id": "MAIN", "extra_cost": 0},
                                       [{"sku": "SHEET", "quantity": 20}], self.user, order["id"])
        self.assertEqual((edited["number"], edited["total_cost"]), (order["number"], 200.0))
        self.assertEqual(self.stock()["SHEET"], (80.0, 10.0)); self.assertEqual(self.stock()["GLUE"], (50.0, 4.0))

    def test_recipe_rules(self):
        with self.assertRaisesRegex(ValueError, "circle"):
            production.save_bom(self.db, {"sku": "SHEET", "lines": [{"sku": "PANEL", "quantity": 1}]}, self.user)
        with self.assertRaisesRegex(ValueError, "itself"):
            production.save_bom(self.db, {"sku": "PANEL", "lines": [{"sku": "PANEL", "quantity": 1}]}, self.user)
        with self.assertRaisesRegex(ValueError, "no recipe"):
            production.plan(self.db, "GLUE", 1)
        with self.assertRaisesRegex(ValueError, "Production"):
            inventory.save_document(self.db, {"doc_type": "production", "doc_date": "10-02-2025", "warehouse_id": "MAIN"}, [{"sku": "PANEL", "quantity": 1}], self.user)
        production.delete_bom(self.db, "PANEL", self.user)
        self.assertEqual(production.list_boms(self.db), [])

    def test_report_and_stock_card(self):
        self.make(25)
        report = production.report(self.db, "01-01-2025", "31-12-2025")
        self.assertEqual(float(report["sections"][1]["rows"][-1][-1]), 590.0)
        self.assertEqual(float(report["sections"][2]["rows"][-1][-1]), 540.0)
        panel = next(i for i in inventory.list_items(self.db) if i["sku"] == "PANEL")
        card = inventory.build_report(self.db, "stock_card", {"item_id": panel["id"], "date_from": "01-01-2025", "date_to": "31-12-2025"})
        self.assertEqual(card["sections"][0]["rows"][1][2], "Production")
        self.assertEqual(float(card["sections"][0]["rows"][-1][-1]), 590.0)
        self.assertEqual(float(inventory.stock_value(self.db, "31-12-2025")), 500 + 160 + 590)


class UpgradeTest(unittest.TestCase):
    def test_new_tables_trigger_the_upgrade(self):
        import database
        source = database._schema_fingerprint.__code__.co_names + database._schema_fingerprint.__code__.co_consts
        self.assertIn("migrate", source)  # inventory.migrate (where the recipe tables are) is part of the marker


if __name__ == "__main__":
    unittest.main()
