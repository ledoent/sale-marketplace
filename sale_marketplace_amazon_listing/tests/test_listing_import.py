# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"


class TestListingImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {"name": "Amazon", "channel_type": "amazon", "amazon_seller_id": "SELLER1"}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1"}
        )

    def _fake_api(self, items):
        api = MagicMock()
        api.search_listings_items.return_value.payload = {
            "items": items,
            "pagination": {},
        }
        return api

    def test_import_creates_binding(self):
        items = [{"sku": "SKU-1", "summaries": [{"asin": "ASIN-1"}]}]
        with patch(f"{_API_PATH}._amazon_get_api", return_value=self._fake_api(items)):
            self.channel.action_amazon_import_listings()
        binding = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.channel.id), ("external_id", "=", "SKU-1")]
        )
        self.assertEqual(len(binding), 1)
        self.assertEqual(binding.product_id, self.product)
        self.assertEqual(binding.asin, "ASIN-1")

    @mute_logger("odoo.addons.sale_marketplace_amazon_listing.models.sale_channel")
    def test_import_skips_unknown_sku(self):
        items = [{"sku": "UNKNOWN", "summaries": []}]
        with patch(f"{_API_PATH}._amazon_get_api", return_value=self._fake_api(items)):
            self.channel.action_amazon_import_listings()
        self.assertFalse(
            self.env["sale.channel.product"].search(
                [("sale_channel_id", "=", self.channel.id)]
            )
        )

    def test_import_requires_seller_id(self):
        self.channel.amazon_seller_id = False
        with self.assertRaises(UserError):
            self.channel.action_amazon_import_listings()
