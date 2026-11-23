import unittest
from unittest.mock import patch

from client import ApiClient


class ReferenceCacheTests(unittest.TestCase):
    def test_reuse_is_scoped_and_writes_invalidate(self):
        client = ApiClient()
        with patch.object(client, "_send", return_value=(200, b'{"items":[1]}')) as send:
            client.select_company_year(1, 2025)
            client.accounts().clear()
            self.assertEqual(client.accounts(), [1])
            self.assertEqual(send.call_count, 1)
            client.select_company_year(1, 2024)
            client.accounts()
            client.select_company_year(2, 2024)
            client.accounts()
            client.token = "second-session"
            client.accounts()
            self.assertEqual(send.call_count, 4)
            client.request("POST", "/api/accounts", {})
            client.accounts()
            self.assertEqual(send.call_count, 6)

    def test_inflight_response_cannot_refill_invalidated_cache(self):
        client = ApiClient()

        def finish_after_invalidation(*args):
            client.clear_cache()
            return 200, b'{"items":[]}'

        with patch.object(client, "_send", side_effect=finish_after_invalidation) as send:
            client.accounts()
            client.accounts()
            self.assertEqual(send.call_count, 2)
