"""2.9.48: Payment & Receipt finds the customer / supplier from the name, the account number or a unique part."""
import unittest
from unittest.mock import MagicMock

from desktop_stage3 import Stage3Mixin


class Var:
    def __init__(self, value=""): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class PaymentPartyTest(unittest.TestCase):
    def setUp(self):
        self.app = Stage3Mixin(); self.app.client = MagicMock()
        self.parties = [{"id": 1, "name": "Client A", "account_number": "411100001"}, {"id": 2, "name": "Client AB", "account_number": "411100002"},
                        {"id": 3, "name": "Supplier X", "account_number": "401100001"}]
        self.form = {"vars": {"party": Var()}, "party_box": {}, "party_map": {f'{p["name"]} | {p["account_number"]}': p for p in self.parties}}

    def resolve(self, text):
        self.form["vars"]["party"].set(text); return self.app.resolve_payment_party(self.form)

    def test_full_text_name_account_and_unique_part(self):
        self.assertEqual(self.resolve("Client A | 411100001")["id"], 1)
        self.assertEqual(self.resolve("client a")["id"], 1)                      # name alone (exact name wins over "Client AB")
        self.assertEqual(self.form["vars"]["party"].get(), "Client A | 411100001")  # the box shows the full choice
        self.assertEqual(self.resolve("401100001")["id"], 3)
        self.assertEqual(self.resolve("suppl")["id"], 3)

    def test_ambiguous_part_asks_to_choose(self):
        with self.assertRaises(ValueError) as caught: self.resolve("client")
        self.assertIn("More than one", str(caught.exception))

    def test_party_added_after_the_screen_opened_is_found(self):
        self.app.client.parties.return_value = self.parties + [{"id": 4, "name": "New Client", "account_number": "411100003"}]
        self.assertEqual(self.resolve("New Client")["id"], 4)
        self.assertIsNone(self.resolve("Nobody"))


if __name__ == "__main__":
    unittest.main()
