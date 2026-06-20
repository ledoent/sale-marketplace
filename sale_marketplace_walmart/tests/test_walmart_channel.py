# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase

_PATH = "odoo.addons.sale_marketplace_walmart.models.sale_channel"


class TestWalmartChannel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart US",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
            }
        )

    def test_is_marketplace(self):
        self.assertTrue(self.channel.is_marketplace)
        self.assertIn("walmart", self.channel._marketplace_channel_types())
        plain = self.env["sale.channel"].create({"name": "Webshop"})
        self.assertFalse(plain.is_marketplace)

    def test_base_url_switches_on_sandbox(self):
        self.assertIn("marketplace.walmartapis.com", self.channel._walmart_base_url())
        self.channel.walmart_sandbox = True
        self.assertIn("sandbox.walmartapis.com", self.channel._walmart_base_url())

    def test_basic_auth_is_base64_of_credentials(self):
        import base64

        decoded = base64.b64decode(self.channel._walmart_basic_auth()).decode()
        self.assertEqual(decoded, "client:secret")

    def test_get_token_returns_access_token(self):
        with patch(f"{_PATH}.requests.post") as post:
            post.return_value.json.return_value = {"access_token": "TOK"}
            post.return_value.raise_for_status.return_value = None
            token = self.channel._walmart_get_token()
        self.assertEqual(token, "TOK")

    def test_request_returns_parsed_json(self):
        with (
            patch(f"{_PATH}.requests.request") as request,
            patch.object(type(self.channel), "_walmart_get_token", return_value="TOK"),
        ):
            request.return_value.json.return_value = {"orders": []}
            request.return_value.content = b"{}"
            request.return_value.raise_for_status.return_value = None
            result = self.channel._walmart_request("GET", "/v3/orders")
        self.assertEqual(result, {"orders": []})

    def test_action_test_connection_success(self):
        with patch.object(type(self.channel), "_walmart_get_token", return_value="TOK"):
            action = self.channel.action_walmart_test_connection()
        self.assertEqual(action["params"]["type"], "success")

    def test_action_test_connection_no_token(self):
        with patch.object(type(self.channel), "_walmart_get_token", return_value=None):
            action = self.channel.action_walmart_test_connection()
        self.assertEqual(action["params"]["type"], "warning")

    def test_market_header_defaults_to_us(self):
        with patch(f"{_PATH}.requests.post") as post:
            post.return_value.json.return_value = {"access_token": "TOK"}
            post.return_value.raise_for_status.return_value = None
            self.channel._walmart_get_token()
        self.assertEqual(post.call_args.kwargs["headers"]["WM_MARKET"], "us")

    def test_market_header_follows_channel_market(self):
        self.channel.walmart_market = "ca"
        with patch(f"{_PATH}.requests.request") as request:
            request.return_value.json.return_value = {}
            request.return_value.content = b"{}"
            request.return_value.raise_for_status.return_value = None
            self.channel._walmart_request("GET", "/v3/orders", token="TOK")
        self.assertEqual(request.call_args.kwargs["headers"]["WM_MARKET"], "ca")

    def test_walmart_log_creates_entry(self):
        log = self.channel._walmart_log(
            "order_import", "hello", level="warning", reference="PO-1"
        )
        self.assertEqual(log.sale_channel_id, self.channel)
        self.assertEqual(log.operation, "order_import")
        self.assertEqual(log.level, "warning")
        self.assertEqual(log.reference, "PO-1")
