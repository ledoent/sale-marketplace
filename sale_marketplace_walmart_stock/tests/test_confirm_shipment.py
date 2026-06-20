# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"

_ORDER = {
    "order": {
        "orderLines": {
            "orderLine": [
                {
                    "lineNumber": "1",
                    "orderLineQuantity": {"unitOfMeasurement": "EACH", "amount": "2"},
                }
            ]
        }
    }
}


class TestConfirmShipment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
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

    def _fake_request(self):
        def _request(method, path, params=None, payload=None, token=None):
            if method == "GET":
                return _ORDER
            return {}

        return _request

    def test_confirm_shipment_marks_lines_shipped(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(
                f"{_MODEL}._walmart_request", side_effect=self._fake_request()
            ) as req,
        ):
            self.channel._walmart_confirm_shipment("PO-1", self.picking.id)

        post_calls = [c for c in req.call_args_list if c.args[0] == "POST"]
        self.assertEqual(len(post_calls), 1)
        path = post_calls[0].args[1]
        self.assertEqual(path, "/v3/orders/PO-1/shipping")
        line = post_calls[0].kwargs["payload"]["orderShipment"]["orderLines"][
            "orderLine"
        ][0]
        status = line["orderLineStatuses"]["orderLineStatus"][0]
        self.assertEqual(line["lineNumber"], "1")
        self.assertEqual(status["status"], "Shipped")
        self.assertEqual(status["trackingInfo"]["trackingNumber"], "TRACK123")
        self.assertEqual(status["statusQuantity"]["amount"], "2")
        self.assertTrue(self.picking.walmart_tracking_pushed)

    @mute_logger("odoo.addons.sale_marketplace_walmart_stock.models.sale_channel")
    def test_confirm_shipment_skips_without_tracking(self):
        self.picking.carrier_tracking_ref = False
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request") as req,
        ):
            self.channel._walmart_confirm_shipment("PO-1", self.picking.id)
        req.assert_not_called()
        self.assertFalse(self.picking.walmart_tracking_pushed)
