# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.extendable.tests.common import ExtendableMixin

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"

_ORDER = {
    "order": {
        "shippingInfo": {
            "postalAddress": {
                "name": "Buyer",
                "address1": "1 Market St",
                "city": "New York",
                "state": "NY",
                "postalCode": "10001",
                "country": "USA",
            }
        },
        "orderLines": {
            "orderLine": [
                {
                    "lineNumber": "1",
                    "item": {"sku": "SKU-1", "productName": "Widget"},
                    "orderLineQuantity": {"unitOfMeasurement": "EACH", "amount": "1"},
                    "charges": {
                        "charge": [
                            {
                                "chargeType": "PRODUCT",
                                "chargeAmount": {"currency": "USD", "amount": 100.0},
                            },
                            {
                                "chargeType": "TAX",
                                "chargeAmount": {"currency": "USD", "amount": 8.0},
                            },
                        ]
                    },
                    "orderLineStatuses": {"orderLineStatus": [{"status": "Created"}]},
                }
            ]
        },
    }
}


class TestTax(TransactionCase, ExtendableMixin):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.init_extendable_registry()
        # Run the auto-enqueued payload-processing job inline.
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.tax = cls.env["account.tax"].create(
            {
                "name": "WM Sale Tax 10%",
                "amount": 10.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "country_id": cls.env.ref("base.us").id,
            }
        )
        # Facilitator fiscal position: map the sale tax to nothing.
        cls.fiscal_position = cls.env["account.fiscal.position"].create(
            {
                "name": "Walmart MFT",
                "tax_ids": [(0, 0, {"tax_src_id": cls.tax.id})],
            }
        )
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
                "warehouse_id": cls.warehouse.id,
                "walmart_fiscal_position_id": cls.fiscal_position.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Widget",
                "default_code": "SKU-1",
                "taxes_id": [(6, 0, [cls.tax.id])],
            }
        )
        cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
            }
        )

    def _import(self, po="PO-1"):
        with patch(f"{_MODEL}._walmart_request", return_value=_ORDER):
            self.channel._walmart_import_order(po)
        return self.env["sale.order"].search(
            [("client_order_ref", "=", po), ("sale_channel_id", "=", self.channel.id)]
        )

    def test_fiscal_position_maps_tax_away(self):
        order = self._import()
        self.assertEqual(len(order), 1)
        self.assertEqual(order.fiscal_position_id, self.fiscal_position)
        # the product's customer tax is mapped to nothing -> no Odoo tax booked
        self.assertFalse(order.order_line.tax_id)
        self.assertEqual(order.order_line.price_unit, 100.0)
        self.assertEqual(order.amount_tax, 0.0)

    def test_collected_tax_is_captured(self):
        order = self._import()
        # the facilitator tax Walmart collected is recorded for reporting
        self.assertEqual(order.walmart_collected_tax, 8.0)

    def test_without_fiscal_position_product_tax_applies(self):
        # Without the guard, Odoo re-charges the product's customer tax — the
        # double-count W5 exists to prevent.
        self.channel.walmart_fiscal_position_id = False
        order = self._import()
        self.assertEqual(order.order_line.tax_id, self.tax)
        self.assertGreater(order.amount_tax, 0.0)
        # collected tax is still captured regardless of the fiscal-position guard
        self.assertEqual(order.walmart_collected_tax, 8.0)
