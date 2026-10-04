# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import gzip
import hashlib
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.sale_marketplace_amazon.tests.sandbox_contract import replay

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_PARENT_ENQUEUE = (
    "odoo.addons.sale_marketplace_amazon_stock.models.stock_picking.StockPicking"
    "._amazon_enqueue_confirm_shipment"
)
DOCUMENT = b"%PDF-1.4 test label"
VALID_LABEL = base64.b64encode(gzip.compress(DOCUMENT)).decode()


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
        "ShipmentId": "S1",
        "TrackingId": "TRACK-1",
        "ShippingService": {
            "CarrierName": "UPS",
            "ShippingServiceName": "UPS Ground",
            "Rate": {"Amount": 7.5},
        },
        "Label": {
            "FileContents": {
                "Contents": contents,
                "FileType": "application/pdf",
                "Checksum": base64.b64encode(
                    hashlib.md5(DOCUMENT, usedforsecurity=False).digest()
                ).decode(),
            }
        },
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
                "amazon_client_id": "test-client",
                "amazon_client_secret": "test-secret",
                "amazon_refresh_token": "test-refresh",
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
                "client_order_ref": "123-1234567-1234567",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "product_uom_qty": 1,
                            "amazon_order_item_id": "ITEM-1",
                        },
                    )
                ],
            }
        )
        order.action_confirm()
        order.picking_ids.move_ids.quantity = 1
        return order.picking_ids[:1]

    def _wizard(self):
        return self.env["sale.channel.buy.shipping.wizard"].create(
            {
                "picking_id": self.picking.id,
                "package_length": 10,
                "package_width": 10,
                "package_height": 10,
            }
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
        self.assertEqual(shipment.amazon_shipment_id, "S1")
        self.assertEqual(base64.b64decode(shipment.label_attachment_id.datas), DOCUMENT)
        with self.assertRaises(UserError):
            wizard.rate_line_ids.action_buy()
        self.assertEqual(api.create_shipment.call_count, 1)

    def test_real_sdk_serializes_required_shipping_fields(self):
        from sp_api.api import MerchantFulfillment

        wizard = self._wizard()
        responses = [
            MagicMock(payload=_rates_payload()),
            MagicMock(payload=_create_payload()),
        ]
        with patch.object(
            MerchantFulfillment, "_request", side_effect=responses
        ) as request:
            wizard.action_get_rates()
            wizard.rate_line_ids.action_buy()
        rate_request, buy_request = request.call_args_list
        details = rate_request.kwargs["data"]["ShipmentRequestDetails"]
        self.assertEqual(
            details["AmazonOrderId"], self.picking.sale_id.client_order_ref
        )
        self.assertEqual(
            details["ItemList"], [{"OrderItemId": "ITEM-1", "Quantity": 1}]
        )
        self.assertEqual(
            details["PackageDimensions"],
            {"Length": 10, "Width": 10, "Height": 10, "Unit": "centimeters"},
        )
        self.assertEqual(
            buy_request.kwargs["data"]["ShippingServiceOfferId"], "offer-1"
        )
        self.assertNotIn("shipping_service_offer_id", buy_request.kwargs["data"])

    def test_changed_package_requires_new_quote(self):
        api = MagicMock()
        api.get_eligible_shipment_services.return_value.payload = _rates_payload()
        wizard = self._wizard()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            wizard.action_get_rates()
            wizard.weight += 1
            with self.assertRaises(UserError):
                wizard.rate_line_ids.action_buy()
        api.create_shipment.assert_not_called()

    def test_missing_dimensions_blocks_rate_request(self):
        wizard = self._wizard()
        wizard.package_height = 0
        with self.assertRaises(UserError):
            wizard.action_get_rates()

    def test_bad_checksum_does_not_persist_a_label(self):
        api = MagicMock()
        api.get_eligible_shipment_services.return_value.payload = _rates_payload()
        payload = _create_payload()
        payload["Label"]["FileContents"]["Checksum"] = "invalid"
        api.create_shipment.return_value.payload = payload
        wizard = self._wizard()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            wizard.action_get_rates()
            with self.assertRaises(UserError):
                wizard.rate_line_ids.action_buy()
        self.assertFalse(self.picking.amazon_label_purchased)

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

    def test_label_purchase_through_sdk_contract(self):
        # Valid constructed label; the published sandbox label is not a usable document.
        self.warehouse.partner_id.write(
            {
                "name": "Warehouse",
                "street": "1 Main St",
                "city": "Seattle",
                "zip": "98101",
                "country_id": self.env.ref("base.us").id,
            }
        )
        wizard = self._wizard()
        responses = {
            "getEligibleShipmentServices": (200, {"payload": _rates_payload()}),
            "createShipment": (200, {"payload": _create_payload()}),
        }
        with replay(responses) as http:
            wizard.action_get_rates()
            wizard.rate_line_ids.action_buy()
        self.assertEqual(self.picking.carrier_tracking_ref, "TRACK-1")
        self.assertTrue(self.picking.amazon_label_purchased)
        self.assertEqual(
            [c["operation"] for c in http.calls],
            ["getEligibleShipmentServices", "createShipment"],
        )

    def test_remote_purchase_timeout_leaves_no_success_flag(self):
        import httpx

        # A timeout is ambiguous: this does not prove Amazon did not buy a label.
        wizard = self._wizard()
        responses = {
            "getEligibleShipmentServices": (200, {"payload": _rates_payload()}),
            "createShipment": httpx.ReadTimeout("simulated lost response"),
        }
        with replay(responses) as http:
            wizard.action_get_rates()
            with self.assertRaises(UserError):
                wizard.rate_line_ids.action_buy()
        self.assertEqual(http.calls[-1]["operation"], "createShipment")
        self.assertFalse(self.picking.amazon_label_purchased)
        self.assertFalse(
            self.env["sale.channel.shipment"].search(
                [("picking_id", "=", self.picking.id)]
            )
        )
