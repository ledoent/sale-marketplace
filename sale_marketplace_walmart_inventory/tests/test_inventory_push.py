# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


class TestInventoryPush(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
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

    def test_push_sends_changed_qty(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request") as req,
        ):
            self.channel._walmart_push_inventory()

        self.assertEqual(req.call_count, 1)
        _, kwargs = req.call_args
        self.assertEqual(kwargs["params"]["sku"], "SKU-1")
        self.assertEqual(kwargs["payload"]["quantity"]["amount"], 7)
        self.assertEqual(self.binding.last_pushed_qty, 7)

    def test_push_skips_unchanged_qty(self):
        self.binding.last_pushed_qty = 7  # already at the computed quantity
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request") as req,
        ):
            self.channel._walmart_push_inventory()
        req.assert_not_called()

    @mute_logger("odoo.addons.sale_marketplace_walmart_inventory.models.sale_channel")
    def test_push_error_isolated_per_binding(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", side_effect=Exception("boom")),
        ):
            self.channel._walmart_push_inventory()
        # Failure is swallowed per binding; qty is not marked as pushed.
        self.assertEqual(self.binding.last_pushed_qty, -1)
        self.assertTrue(self.channel.last_inventory_sync_date)
