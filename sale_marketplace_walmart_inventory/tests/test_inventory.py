# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestInventoryQty(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart US",
                "channel_type": "walmart",
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
        self.assertEqual(self.channel._walmart_compute_qty(self.product), 10)

    def test_compute_qty_min_reserve(self):
        self.channel.inventory_min_reserve = 3
        self.assertEqual(self.channel._walmart_compute_qty(self.product), 7)

    def test_compute_qty_expose_ratio(self):
        self.channel.inventory_expose_ratio = 0.5
        self.assertEqual(self.channel._walmart_compute_qty(self.product), 5)

    def test_compute_qty_aggregates_configured_locations(self):
        # with multiple fulfillment locations, free qty is summed across them
        loc2 = self.env["stock.location"].create(
            {
                "name": "WM Loc 2",
                "usage": "internal",
                "location_id": self.warehouse.view_location_id.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(self.product, loc2, 5)
        self.channel.inventory_location_ids = [
            (6, 0, [self.warehouse.lot_stock_id.id, loc2.id])
        ]
        self.assertEqual(self.channel._walmart_compute_qty(self.product), 15)

    def test_expose_ratio_constraint(self):
        with self.assertRaises(ValidationError):
            self.channel.inventory_expose_ratio = 1.5

    def test_min_reserve_constraint(self):
        with self.assertRaises(ValidationError):
            self.channel.inventory_min_reserve = -1
