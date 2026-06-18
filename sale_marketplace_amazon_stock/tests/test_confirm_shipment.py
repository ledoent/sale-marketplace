# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase

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
        cls.picking = cls.env["stock.picking"].create(
            {
                "picking_type_id": cls.wh.out_type_id.id,
                "location_id": cls.wh.lot_stock_id.id,
                "location_dest_id": cls.env.ref("stock.stock_location_customers").id,
                "carrier_tracking_ref": "TRACK123",
            }
        )
        cls.picking.date_done = fields.Datetime.now()

    def test_confirm_shipment_passes_body_as_kwargs(self):
        api = MagicMock()
        api.get_order_items.return_value.payload = {
            "OrderItems": [{"OrderItemId": "oi-1", "QuantityOrdered": 1}]
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
