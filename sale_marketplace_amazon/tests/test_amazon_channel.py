# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestAmazonChannel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon US",
                "channel_type": "amazon",
                "amazon_client_id": "client",
                "amazon_client_secret": "secret",
                "amazon_refresh_token": "token",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
            }
        )

    def test_is_marketplace(self):
        self.assertTrue(self.channel.is_marketplace)
        plain = self.env["sale.channel"].create({"name": "Webshop"})
        self.assertFalse(plain.is_marketplace)

    def test_credentials_payload(self):
        creds = self.channel._amazon_get_credentials()
        self.assertEqual(creds["lwa_app_id"], "client")
        self.assertEqual(creds["lwa_client_secret"], "secret")
        self.assertEqual(creds["refresh_token"], "token")
