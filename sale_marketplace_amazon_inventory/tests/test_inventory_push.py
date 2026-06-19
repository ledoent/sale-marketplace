# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"


class TestInventoryPush(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_seller_id": "SELLER1",
                "warehouse_id": cls.wh.id,
                "inventory_sync_enabled": True,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.wh.lot_stock_id, 7
        )
        cls.binding = cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
            }
        )

    def test_push_patches_changed_qty(self):
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_push_inventory()

        self.assertEqual(api.patch_listings_item.call_count, 1)
        _, kwargs = api.patch_listings_item.call_args
        self.assertEqual(kwargs["sellerId"], "SELLER1")
        self.assertEqual(kwargs["sku"], "SKU-1")
        value = kwargs["body"]["patches"][0]["value"][0]
        self.assertEqual(value["quantity"], 7)
        self.assertEqual(self.binding.last_pushed_qty, 7)

    def test_push_skips_unchanged_qty(self):
        self.binding.last_pushed_qty = 7  # already at the computed quantity
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_push_inventory()
        api.patch_listings_item.assert_not_called()
