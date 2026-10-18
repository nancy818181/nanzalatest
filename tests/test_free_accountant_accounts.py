import tempfile
import unittest
from pathlib import Path

import tests_setup  # noqa: F401
from database import Database
from free_accounts import CHART_PATH, CHART_RECORDS, REAL_CHART, suggest_and_autocreate


class FakeAccountClient:
    def __init__(self):
        self.rows = [
            {"code": code, "name_en": row["name_en"], "name_ar": row["name_ar"],
             "name_fr": row["name_fr"], "type": row["type"], "parent_code": row["parent_code"]}
            for code, row in CHART_RECORDS.items()
        ]

    def accounts(self):
        return [dict(row) for row in self.rows]

    def save_account(self, item):
        self.rows.append(dict(item))
        return dict(item)


class DatabaseAccountClient:
    def __init__(self, database, user_id):
        self.database = database
        self.user_id = user_id

    def accounts(self):
        return self.database.list_accounts()

    def save_account(self, item):
        return self.database.save_account(item, self.user_id)


class FreeAccountantChartTests(unittest.TestCase):
    def test_chart_is_discovered_and_contains_real_base_accounts(self):
        self.assertTrue(CHART_PATH.is_file())
        self.assertGreater(len(REAL_CHART), 300)
        self.assertEqual(
            {code for code in ("6263.4", "6263.3", "6263.1", "6261.5", "6261.1", "6262",
                               "6264.1", "6264.2", "6011", "4111", "4011", "4211")
             if code in REAL_CHART},
            {"6263.4", "6263.3", "6263.1", "6261.5", "6261.1", "6262",
             "6264.1", "6264.2", "6011", "4111", "4011", "4211"},
        )

    def test_electricity_suggestion_and_two_detail_accounts(self):
        client = FakeAccountClient()
        plain = suggest_and_autocreate("كهرباء", client)
        self.assertEqual(plain["base_code"], "6263.4")
        self.assertFalse(plain["auto_created"])
        self.assertIsNone(plain["new_9digit_code"])

        first = suggest_and_autocreate("كهرباء المولد", client)
        second = suggest_and_autocreate("كهرباء الادارة", client)
        self.assertEqual((first["new_9digit_code"], first["auto_created"]), ("626340001", True))
        self.assertEqual((second["new_9digit_code"], second["auto_created"]), ("626340002", True))

    def test_rent_detail_and_provider_description(self):
        client = FakeAccountClient()
        rent = suggest_and_autocreate("ايجار المكتب", client)
        provider_invoice = suggest_and_autocreate("فاتورة ogero انترنت", client)
        self.assertEqual((rent["base_code"], rent["new_9digit_code"], rent["auto_created"]),
                         ("6263.1", "626310001", True))
        self.assertEqual(provider_invoice["base_code"], "6261.5")
        self.assertFalse(provider_invoice["auto_created"])
        self.assertIsNone(provider_invoice["new_9digit_code"])

    def test_repeated_detail_reuses_existing_account(self):
        client = FakeAccountClient()
        first = suggest_and_autocreate("كهرباء المولد", client)
        repeated = suggest_and_autocreate("كهرباء المولد", client)
        self.assertTrue(first["auto_created"])
        self.assertEqual(repeated["new_9digit_code"], "626340001")
        self.assertFalse(repeated["auto_created"])
        self.assertEqual(
            sum(row.get("name_ar") == "كهرباء المولد" for row in client.rows),
            1,
        )

    def test_account_creation_persists_arabic_and_french_names(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "accounts.db")
            database.initialize("secret")
            user = database.user_for_token(database.login("admin", "secret")["token"])
            account = database.save_account({
                "code": "626340001",
                "name_en": "Electricity - Generator",
                "name_ar": "كهرباء المولد",
                "name_fr": "Électricité - Générateur",
                "parent_code": "6263.4",
                "type": "expense",
            }, user["id"])
            saved = next(row for row in database.list_accounts() if row["code"] == account["code"])
            self.assertEqual(saved["parent_code"], "6263.4")
            self.assertEqual(saved["name_ar"], "كهرباء المولد")
            self.assertEqual(saved["name_fr"], "Électricité - Générateur")

    def test_suggestion_creates_and_reuses_a_real_company_account(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "company.db")
            database.initialize("secret")
            user = database.user_for_token(database.login("admin", "secret")["token"])
            client = DatabaseAccountClient(database, user["id"])
            first = suggest_and_autocreate("كهرباء المولد", client)
            repeated = suggest_and_autocreate("كهرباء المولد", client)
            self.assertEqual((first["new_9digit_code"], first["auto_created"]), ("626340001", True))
            self.assertEqual((repeated["new_9digit_code"], repeated["auto_created"]), ("626340001", False))
            saved = next(row for row in database.list_accounts() if row["code"] == "626340001")
            self.assertEqual(saved["parent_code"], "6263.4")
            self.assertEqual(saved["name_ar"], "كهرباء المولد")


if __name__ == "__main__":
    unittest.main()
