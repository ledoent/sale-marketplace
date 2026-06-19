# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = (
    "odoo.addons.sale_marketplace_amazon_mcf.models.sale_channel_fulfillment_order"
)


def _status_payload(status="COMPLETE", shipments=1, packages=1):
    ship = []
    for s in range(shipments):
        ship.append(
            {
                "fulfillmentShipmentPackage": [
                    {"trackingNumber": f"T{s}-{p}", "carrierCode": "UPS"}
                    for p in range(packages)
                ]
            }
        )
    return {
        "fulfillmentOrder": {"fulfillmentOrderStatus": status},
        "fulfillmentShipments": ship,
    }


class TestMcf(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_seller_id": "SELLER1",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "warehouse_id": cls.warehouse.id,
                "mcf_default_speed": "Standard",
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Buyer", "street": "1 St", "city": "NYC", "zip": "10001"}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1", "is_storable": True}
        )
        cls.env["sale.channel.fba.inventory"].create(
            {
                "sale_channel_id": cls.channel.id,
                "seller_sku": "SKU-1",
                "product_id": cls.product.id,
            }
        )
        cls.picking = cls._make_picking(cls.product, qty=2)

    @classmethod
    def _make_picking(cls, product, qty=1):
        order = cls.env["sale.order"].create(
            {
                "partner_id": cls.customer.id,
                "order_line": [
                    (0, 0, {"product_id": product.id, "product_uom_qty": qty})
                ],
            }
        )
        order.action_confirm()
        return order.picking_ids[:1]

    def _create_order(self, name="FO-1"):
        return self.env["sale.channel.fulfillment.order"].create(
            {
                "name": name,
                "sale_channel_id": self.channel.id,
                "picking_id": self.picking.id,
                "partner_id": self.customer.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "seller_sku": "SKU-1",
                            "quantity": 1,
                        },
                    )
                ],
            }
        )

    # ---- build from picking ----
    def test_fulfill_creates_draft(self):
        action = self.picking.action_amz_mcf_fulfill()
        order = self.env["sale.channel.fulfillment.order"].browse(action["res_id"])
        self.assertEqual(order.state, "draft")
        self.assertEqual(order.sale_channel_id, self.channel)
        self.assertEqual(len(order.line_ids), 1)
        self.assertEqual(order.line_ids.seller_sku, "SKU-1")
        self.assertEqual(order.line_ids.quantity, 2)

    def test_fulfill_requires_fba_sku(self):
        no_fba = self.env["product.product"].create(
            {"name": "NoFBA", "is_storable": True}
        )
        picking = self._make_picking(no_fba, qty=1)
        with self.assertRaises(UserError):
            picking.action_amz_mcf_fulfill()

    # ---- submit / status / cancel ----
    def test_submit_calls_api(self):
        order = self._create_order()
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            order.action_submit()
        self.assertEqual(order.state, "submitted")
        self.assertTrue(api.create_fulfillment_order.called)
        _args, kwargs = api.create_fulfillment_order.call_args
        self.assertEqual(kwargs["items"][0]["sellerSku"], "SKU-1")

    def test_submit_requires_lines(self):
        order = self._create_order()
        order.line_ids.unlink()
        with self.assertRaises(UserError):
            order.action_submit()

    def test_check_status_complete_sets_tracking(self):
        order = self._create_order()
        order.state = "submitted"
        api = MagicMock()
        api.get_fulfillment_order.return_value.payload = _status_payload()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            order.action_check_status()
        self.assertEqual(order.state, "complete")
        self.assertEqual(order.tracking_numbers, "T0-0")
        self.assertEqual(self.picking.carrier_tracking_ref, "T0-0")

    def test_check_status_multi_shipment_collects_all_tracking(self):
        order = self._create_order()
        order.state = "submitted"
        api = MagicMock()
        api.get_fulfillment_order.return_value.payload = _status_payload(
            shipments=2, packages=2
        )
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            order.action_check_status()
        self.assertEqual(order.tracking_numbers, "T0-0, T0-1, T1-0, T1-1")

    def test_cancel_submitted_calls_api(self):
        order = self._create_order()
        order.state = "submitted"
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            order.action_cancel()
        self.assertEqual(order.state, "cancelled")
        self.assertTrue(api.cancel_fulfillment_order.called)

    def test_cancel_draft_skips_api(self):
        order = self._create_order()
        with patch(f"{_API_PATH}._amazon_get_api") as get_api:
            order.action_cancel()
        self.assertEqual(order.state, "cancelled")
        get_api.assert_not_called()

    @mute_logger(_MODEL_PATH)
    def test_cron_isolates_failures(self):
        order1 = self._create_order("FO-1")
        order2 = self._create_order("FO-2")
        (order1 | order2).write({"state": "submitted"})
        api = MagicMock()
        api.get_fulfillment_order.side_effect = [
            Exception("boom"),
            MagicMock(payload=_status_payload()),
        ]
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.env["sale.channel.fulfillment.order"]._cron_amazon_sync_mcf_status()
        completed = (order1 | order2).filtered(lambda o: o.state == "complete")
        self.assertEqual(len(completed), 1)  # one failed, one succeeded
