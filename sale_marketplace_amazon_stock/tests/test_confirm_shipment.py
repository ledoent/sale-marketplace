# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.sale_marketplace_amazon.tests.sandbox_contract import replay

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"


class TestConfirmShipment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
            }
        )
        cls.wh = cls.env["stock.warehouse"].search([], limit=1)
        cls.product = cls.env["product.product"].create({"name": "Amazon widget"})
        cls.partner = cls.env["res.partner"].create({"name": "Buyer"})
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "sale_channel_id": cls.channel.id,
                "client_order_ref": "ORDER-1",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "product_uom_qty": 3,
                            "amazon_order_item_id": "oi-1",
                        },
                    )
                ],
            }
        )
        cls.order.action_confirm()
        cls.picking = cls.order.picking_ids
        cls.picking.move_ids.write({"quantity": 1, "picked": True})
        cls.picking._action_done()
        cls.picking.carrier_tracking_ref = "TRACK123"

    def test_confirm_shipment_passes_body_as_kwargs(self):
        api = MagicMock()
        api.get_order_items.return_value.payload = {
            "OrderItems": [{"OrderItemId": "oi-1", "QuantityOrdered": 3}]
        }
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_confirm_shipment("ORDER-1", self.picking.id)

        # sp_api confirm_shipment sends **kwargs as the POST body: the request
        # fields must be top-level kwargs, never wrapped in payload=.
        self.assertEqual(api.confirm_shipment.call_count, 1)
        args, kwargs = api.confirm_shipment.call_args
        self.assertEqual(args, ("ORDER-1",))
        self.assertNotIn("payload", kwargs)
        self.assertEqual(kwargs["marketplaceId"], "ATVPDKIKX0DER")
        self.assertEqual(kwargs["packageDetail"]["trackingNumber"], "TRACK123")
        self.assertEqual(
            kwargs["packageDetail"]["orderItems"],
            [{"orderItemId": "oi-1", "quantity": 1}],
        )
        self.assertTrue(self.picking.amazon_tracking_pushed)
        self.assertEqual(
            kwargs["packageDetail"]["packageReferenceId"], str(self.picking.id)
        )
        api.get_order_items.assert_not_called()

    def test_backorder_confirms_only_remaining_quantity(self):
        backorder = self.order.picking_ids - self.picking
        self.assertEqual(len(backorder), 1)
        backorder.move_ids.write({"quantity": 2, "picked": True})
        backorder._action_done()
        backorder.carrier_tracking_ref = "TRACK456"
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_confirm_shipment("ORDER-1", backorder.id)
        self.assertEqual(
            api.confirm_shipment.call_args.kwargs["packageDetail"]["orderItems"],
            [{"orderItemId": "oi-1", "quantity": 2}],
        )

    def test_unfinished_delivery_cannot_be_confirmed(self):
        backorder = self.order.picking_ids - self.picking
        with self.assertRaises(UserError):
            self.channel._amazon_confirm_shipment("ORDER-1", backorder.id)

    def test_missing_item_mapping_blocks_api_call(self):
        self.order.order_line.amazon_order_item_id = False
        with patch(f"{_API_PATH}._amazon_get_api") as get_api:
            with self.assertRaises(UserError):
                self.channel._amazon_confirm_shipment("ORDER-1", self.picking.id)
        get_api.assert_not_called()

    def test_wrong_order_cannot_be_confirmed(self):
        with self.assertRaises(UserError):
            self.channel._amazon_confirm_shipment("OTHER-ORDER", self.picking.id)

    def test_completed_quantity_through_sdk_contract(self):
        with replay() as http:
            self.channel._amazon_confirm_shipment("ORDER-1", self.picking.id)
        self.assertEqual(
            http.calls[0]["body"]["packageDetail"]["orderItems"],
            [{"orderItemId": "oi-1", "quantity": 1}],
        )
        self.assertTrue(self.picking.amazon_tracking_pushed)
