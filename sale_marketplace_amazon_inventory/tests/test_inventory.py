# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase

from odoo.addons.sale_marketplace_amazon.tests.sandbox_contract import replay


class TestInventoryQty(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon US",
                "channel_type": "amazon",
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 10
        )

    def test_compute_qty_full(self):
        self.assertEqual(self.channel._amazon_compute_qty(self.product), 10)

    def test_compute_qty_min_reserve(self):
        self.channel.inventory_min_reserve = 3
        self.assertEqual(self.channel._amazon_compute_qty(self.product), 7)

    def test_compute_qty_expose_ratio(self):
        self.channel.inventory_expose_ratio = 0.5
        self.assertEqual(self.channel._amazon_compute_qty(self.product), 5)

    def test_inventory_patch_through_sdk_contract(self):
        self.channel.amazon_seller_id = "SELLER1"
        binding = self.env["sale.channel.product"].create(
            {
                "sale_channel_id": self.channel.id,
                "product_id": self.product.id,
                "external_id": "SKU-1",
            }
        )
        with replay() as http:
            self.channel._amazon_push_inventory()
        self.assertEqual(binding.last_pushed_qty, 10)
        self.assertEqual(http.calls[0]["operation"], "patchListingsItem")
        self.assertEqual(
            http.calls[0]["body"]["patches"][0]["value"][0]["quantity"], 10
        )
