# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.extendable.tests.common import ExtendableMixin

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"


class TestImportOrders(TransactionCase, ExtendableMixin):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.init_extendable_registry()
        # Run the auto-enqueued import job inline instead of via queue_job.
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon US",
                "channel_type": "amazon",
                "amazon_client_id": "client",
                "amazon_client_secret": "secret",
                "amazon_refresh_token": "token",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "amazon_sandbox": True,
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "WIDGET-1"}
        )
        cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "WIDGET-1",
            }
        )

    def _fake_api(self):
        api = MagicMock()
        api.get_order_items.return_value.payload = {
            "OrderStatus": "Unshipped",
            "OrderItems": [
                {
                    "SellerSKU": "WIDGET-1",
                    "OrderItemId": "oi-1",
                    "QuantityOrdered": 2,
                    "ItemPrice": {"Amount": "20.00"},
                    "Title": "Widget",
                }
            ],
        }
        api.get_order_address.return_value.payload = {
            "ShippingAddress": {
                "Name": "Jane Buyer",
                "AddressLine1": "1 Market St",
                "City": "New York",
                "StateOrRegion": "NY",
                "PostalCode": "10001",
                "CountryCode": "US",
            }
        }
        return api

    def test_import_order_creates_sale_order(self):
        with patch(f"{_API_PATH}._amazon_get_api", return_value=self._fake_api()):
            self.channel._amazon_import_order("ORDER-1")

        payload = self.env["sale.import.payload"].search(
            [("sale_channel_id", "=", self.channel.id)], order="id desc", limit=1
        )
        self.assertEqual(payload.state, "done", f"import failed: {payload.state_info}")
        order = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", "ORDER-1"),
                ("sale_channel_id", "=", self.channel.id),
            ]
        )
        self.assertEqual(len(order), 1)
        self.assertEqual(order.warehouse_id, self.warehouse)
        self.assertEqual(order.order_line.product_id, self.product)
        self.assertEqual(order.order_line.product_uom_qty, 2)
        self.assertEqual(order.order_line.price_unit, 10.0)
        binding = self.env["sale.channel.partner"].search(
            [("external_id", "=", "ORDER-1"), ("sale_channel_id", "=", self.channel.id)]
        )
        self.assertEqual(len(binding), 1)
        self.assertEqual(binding.partner_id, order.partner_id)

    def test_import_paginates_order_items(self):
        p2 = self.env["product.product"].create(
            {"name": "Gadget", "default_code": "WIDGET-2"}
        )
        self.env["sale.channel.product"].create(
            {
                "sale_channel_id": self.channel.id,
                "product_id": p2.id,
                "external_id": "WIDGET-2",
            }
        )
        api = MagicMock()
        page1 = MagicMock()
        page1.payload = {
            "OrderItems": [
                {
                    "SellerSKU": "WIDGET-1",
                    "OrderItemId": "oi-1",
                    "QuantityOrdered": 1,
                    "ItemPrice": {"Amount": "10.00"},
                }
            ],
            "NextToken": "page2",
        }
        page2 = MagicMock()
        page2.payload = {
            "OrderItems": [
                {
                    "SellerSKU": "WIDGET-2",
                    "OrderItemId": "oi-2",
                    "QuantityOrdered": 2,
                    "ItemPrice": {"Amount": "40.00"},
                }
            ]
        }
        api.get_order_items.side_effect = [page1, page2]
        api.get_order_address.return_value.payload = {
            "ShippingAddress": {
                "Name": "Jane Buyer",
                "AddressLine1": "1 Market St",
                "City": "New York",
                "StateOrRegion": "NY",
                "PostalCode": "10001",
                "CountryCode": "US",
            }
        }
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_import_order("ORDER-PAGED")

        order = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", "ORDER-PAGED"),
                ("sale_channel_id", "=", self.channel.id),
            ]
        )
        self.assertEqual(api.get_order_items.call_count, 2)
        self.assertEqual(len(order.order_line), 2)
        self.assertEqual(set(order.order_line.product_id.ids), {self.product.id, p2.id})

    def test_import_order_is_idempotent(self):
        with patch(f"{_API_PATH}._amazon_get_api", return_value=self._fake_api()):
            self.channel._amazon_import_order("ORDER-2")
            self.channel._amazon_import_order("ORDER-2")
        orders = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", "ORDER-2"),
                ("sale_channel_id", "=", self.channel.id),
            ]
        )
        self.assertEqual(len(orders), 1)
