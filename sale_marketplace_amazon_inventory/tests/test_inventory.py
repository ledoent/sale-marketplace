# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


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
