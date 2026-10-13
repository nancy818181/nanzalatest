"""2.9.50: filters take any combination of values (the 1st and the 3rd, two, five ...)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import inventory
from database import Database
from multi_select import chosen_values, matches


class ChoiceTextTest(unittest.TestCase):
    def test_text_round_trip(self):
        self.assertEqual(chosen_values("All"), []); self.assertEqual(chosen_values(""), [])
        self.assertEqual(chosen_values("Beirut"), ["Beirut"]); self.assertEqual(chosen_values("Beirut; Tripoli; Saida"), ["Beirut", "Tripoli", "Saida"])
        self.assertTrue(matches("tripoli", "Beirut; Tripoli")); self.assertFalse(matches("Zahle", "Beirut; Tripoli")); self.assertTrue(matches("x", "All"))


class InventoryMultiFilterTest(unittest.TestCase):
    def test_brands_categories_and_projects_in_any_combination(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "f.db"); db.initialize("secret")
            user = db.user_for_token(db.login("admin", "secret")["token"])["id"]
            skus = {}
            for name, brand in (("A", "Fundermax"), ("B", "Alucobond"), ("C", "Egger"), ("D", "Kronospan")):
                item = inventory.save_item(db, {"name": name, "unit": "sheet", "brand": brand}, user); skus[brand] = item["sku"]
                inventory.save_document(db, {"doc_type": "receipt", "doc_date": "2026-03-01", "warehouse_id": "MAIN"}, [{"sku": item["sku"], "quantity": 2, "unit_cost": 10}], user)
            rows = inventory.build_report(db, "valuation", {"date_to": "31-03-2026", "brand": ["Fundermax", "egger"]})["sections"][0]["rows"]
            codes = {r[0] for r in rows}
            self.assertTrue({skus["Fundermax"], skus["Egger"]} <= codes); self.assertFalse({skus["Alucobond"], skus["Kronospan"]} & codes)
            single = inventory.build_report(db, "valuation", {"date_to": "31-03-2026", "brand": "Alucobond"})["sections"][0]["rows"]
            self.assertIn(skus["Alucobond"], {r[0] for r in single})
            meta = inventory.build_report(db, "valuation", {"date_to": "31-03-2026", "brand": ["Fundermax", "Egger"]})["meta"]
            self.assertTrue(any("Fundermax, Egger" in line for line in meta), meta)
            with db.connect() as c:
                p1 = c.execute("INSERT INTO projects(code,name,created_at) VALUES('P1','Tower','2026-01-01')").lastrowid
                p2 = c.execute("INSERT INTO projects(code,name,created_at) VALUES('P2','Villa','2026-01-01')").lastrowid
                c.execute("INSERT INTO projects(code,name,created_at) VALUES('P3','Mall','2026-01-01')")
            numbers = []
            for code in ("P1", "P2", "P3"):
                numbers.append(inventory.save_document(db, {"doc_type": "issue", "doc_date": "2026-03-03", "warehouse_id": "MAIN", "project_id": code},
                                                       [{"sku": skus["Egger"], "quantity": 0.5}], user)["number"])
            moves = inventory.build_report(db, "movements", {"date_from": "01-01-2026", "date_to": "31-03-2026", "project_id": [str(p1), str(p2)]})["sections"][0]["rows"]
            self.assertEqual(sorted(r[1] for r in moves), sorted(numbers[:2]))
            db.release()


class FinancialFilterTest(unittest.TestCase):
    def test_ledger_lines_kept_for_the_ticked_values(self):
        try:
            import tkinter as tk
            import desktop
        except ImportError as exc: self.skipTest(str(exc))
        try: root = tk.Tk()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            root.withdraw()
            app = SimpleNamespace(fin_filters={"branch": tk.StringVar(master=root, value="Beirut; Saida"), "party": tk.StringVar(master=root, value="All")},
                                  shown_financial_filters=lambda: ["branch", "party"])
            ok = lambda row: desktop.SaberApp.financial_filter_ok(app, row)
            self.assertTrue(ok({"branch_name": "Beirut"})); self.assertTrue(ok({"branch_name": "saida"})); self.assertFalse(ok({"branch_name": "Tripoli"}))
            from multi_select import MultiSelect
            changed = []; box = MultiSelect(root, app.fin_filters["party"], on_change=lambda: changed.append(1))
            box["values"] = ["All", "Client A", "Client B", "Client C"]
            self.assertEqual(box["values"], ("All", "Client A", "Client B", "Client C"))
            box.set_choices(["Client A", "Client C"]); self.assertEqual(app.fin_filters["party"].get(), "Client A; Client C")
            box.set_choices(["Client A", "Client B", "Client C"]); self.assertEqual(app.fin_filters["party"].get(), "All")
            self.assertEqual(len(changed), 2)
            box.open(); root.update(); self.assertTrue(box.popup.winfo_exists()); box.popup.destroy()
        finally: root.destroy()


if __name__ == "__main__":
    unittest.main()
