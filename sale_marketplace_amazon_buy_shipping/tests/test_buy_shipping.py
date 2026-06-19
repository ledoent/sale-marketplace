# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_PARENT_ENQUEUE = (
    "odoo.addons.sale_marketplace_amazon_stock.models.stock_picking.StockPicking"
    "._amazon_enqueue_confirm_shipment"
)
VALID_LABEL = base64.b64encode(b"%PDF-1.4 test label").decode()


def _rates_payload():
    return {
        "ShippingServiceList": [
            {
                "ShippingServiceId": "svc-ups",
                "ShippingServiceOfferId": "offer-1",
                "CarrierName": "UPS",
                "ShippingServiceName": "UPS Ground",
                "Rate": {"Amount": 7.5, "CurrencyCode": "USD"},
            }
        ]
    }


def _create_payload(contents=VALID_LABEL):
    return {
        "AmazonShipmentId": "S1",
        "TrackingId": "TRACK-1",
        "ShippingService": {
            "CarrierName": "UPS",
            "ShippingServiceName": "UPS Ground",
            "Rate": {"Amount": 7.5},
        },
        "Label": {"FileContents": {"Contents": contents}},
    }


class TestBuyShipping(TransactionCase):
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
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Buyer", "street": "1 Market St", "city": "NYC", "zip": "10001"}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "is_storable": True, "weight": 2.0}
        )
        cls.picking = cls._make_amazon_picking(cls.channel)

    @classmethod
    def _make_amazon_picking(cls, channel):
        order = cls.env["sale.order"].create(
            {
                "partner_id": cls.customer.id,
                "sale_channel_id": channel.id,
                "order_line": [
                    (0, 0, {"product_id": cls.product.id, "product_uom_qty": 1})
                ],
            }
        )
        order.action_confirm()
        return order.picking_ids[:1]

    def _wizard(self):
        return self.env["sale.channel.buy.shipping.wizard"].create(
            {"picking_id": self.picking.id}
        )

    def test_is_amazon_order_flag(self):
        self.assertTrue(self.picking.is_amazon_order)

    def test_get_rates_populates_options(self):
        api = MagicMock()
        api.get_eligible_shipment_services.return_value.payload = _rates_payload()
        wizard = self._wizard()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            wizard.action_get_rates()
        self.assertEqual(len(wizard.rate_line_ids), 1)
        self.assertEqual(wizard.rate_line_ids.carrier_name, "UPS")
        self.assertEqual(wizard.rate_line_ids.amount, 7.5)

    def test_buy_label_sets_tracking_and_shipment(self):
        api = MagicMock()
        api.get_eligible_shipment_services.return_value.payload = _rates_payload()
        api.create_shipment.return_value.payload = _create_payload()
        wizard = self._wizard()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            wizard.action_get_rates()
            wizard.rate_line_ids.action_buy()
        self.assertEqual(self.picking.carrier_tracking_ref, "TRACK-1")
        self.assertTrue(self.picking.amazon_label_purchased)
        shipment = self.env["sale.channel.shipment"].search(
            [("picking_id", "=", self.picking.id)]
        )
        self.assertEqual(len(shipment), 1)
        self.assertEqual(shipment.tracking_number, "TRACK-1")
        self.assertTrue(shipment.label_attachment_id)

    def test_buy_invalid_label_is_atomic(self):
        api = MagicMock()
        api.get_eligible_shipment_services.return_value.payload = _rates_payload()
        api.create_shipment.return_value.payload = _create_payload(
            contents="!!!not-base64!!!"
        )
        wizard = self._wizard()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            wizard.action_get_rates()
            with self.assertRaises(UserError):
                wizard.rate_line_ids.action_buy()
        # nothing persisted: no shipment, tracking unchanged, flag not set
        self.assertFalse(
            self.env["sale.channel.shipment"].search(
                [("picking_id", "=", self.picking.id)]
            )
        )
        self.assertFalse(self.picking.amazon_label_purchased)

    def test_get_rates_no_channel_raises(self):
        plain = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "partner_id": self.customer.id,
            }
        )
        wizard = self.env["sale.channel.buy.shipping.wizard"].create(
            {"picking_id": plain.id}
        )
        with self.assertRaises(UserError):
            wizard.action_get_rates()

    def test_purchased_picking_skips_double_confirm(self):
        self.picking.write(
            {"carrier_tracking_ref": "T1", "amazon_label_purchased": True}
        )
        with patch(_PARENT_ENQUEUE) as parent:
            self.picking._amazon_enqueue_confirm_shipment()
        parent.assert_not_called()

    def test_unpurchased_picking_calls_confirm(self):
        self.picking.write(
            {"carrier_tracking_ref": "T1", "amazon_label_purchased": False}
        )
        with patch(_PARENT_ENQUEUE) as parent:
            self.picking._amazon_enqueue_confirm_shipment()
        parent.assert_called_once()
