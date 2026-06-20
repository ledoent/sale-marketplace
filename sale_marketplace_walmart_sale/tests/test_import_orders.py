# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.extendable.tests.common import ExtendableMixin
from odoo.addons.queue_job.tests.common import trap_jobs

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


def _order(po_id="PO-1", line_status="Created", qty="2", amount=20.00, country="USA"):
    return {
        "purchaseOrderId": po_id,
        "shippingInfo": {
            "phone": "555-1234",
            "postalAddress": {
                "name": "Jane Buyer",
                "address1": "1 Market St",
                "city": "New York",
                "state": "NY",
                "postalCode": "10001",
                "country": country,
            },
        },
        "orderLines": {
            "orderLine": [
                {
                    "lineNumber": "1",
                    "item": {"productName": "Widget", "sku": "WIDGET-1"},
                    "charges": {
                        "charge": [
                            {
                                "chargeType": "PRODUCT",
                                "chargeAmount": {"currency": "USD", "amount": amount},
                            },
                            {
                                "chargeType": "TAX",
                                "chargeAmount": {"currency": "USD", "amount": 1.50},
                            },
                        ]
                    },
                    "orderLineQuantity": {"unitOfMeasurement": "EACH", "amount": qty},
                    "orderLineStatuses": {"orderLineStatus": [{"status": line_status}]},
                }
            ]
        },
    }


class TestImportOrders(TransactionCase, ExtendableMixin):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.init_extendable_registry()
        # Run the auto-enqueued payload-processing job inline.
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart US",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
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

    def test_import_order_creates_sale_order(self):
        with patch(f"{_MODEL}._walmart_request", return_value={"order": _order()}):
            self.channel._walmart_import_order("PO-1")

        payload = self.env["sale.import.payload"].search(
            [("sale_channel_id", "=", self.channel.id)], order="id desc", limit=1
        )
        self.assertEqual(payload.state, "done", f"import failed: {payload.state_info}")
        order = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", "PO-1"),
                ("sale_channel_id", "=", self.channel.id),
            ]
        )
        self.assertEqual(len(order), 1)
        self.assertEqual(order.warehouse_id, self.warehouse)
        self.assertEqual(order.order_line.product_id, self.product)
        self.assertEqual(order.order_line.product_uom_qty, 2)
        # PRODUCT charge 20.00 over qty 2 -> unit 10.00 (TAX charge excluded).
        self.assertEqual(order.order_line.price_unit, 10.0)
        binding = self.env["sale.channel.partner"].search(
            [("external_id", "=", "PO-1"), ("sale_channel_id", "=", self.channel.id)]
        )
        self.assertEqual(len(binding), 1)
        self.assertEqual(binding.partner_id, order.partner_id)

    def test_import_order_is_idempotent(self):
        with patch(
            f"{_MODEL}._walmart_request", return_value={"order": _order("PO-2")}
        ):
            self.channel._walmart_import_order("PO-2")
            self.channel._walmart_import_order("PO-2")
        orders = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", "PO-2"),
                ("sale_channel_id", "=", self.channel.id),
            ]
        )
        self.assertEqual(len(orders), 1)

    def test_fully_cancelled_order_is_skipped(self):
        cancelled = _order("PO-CANCEL", line_status="Cancelled")
        with patch(f"{_MODEL}._walmart_request", return_value={"order": cancelled}):
            result = self.channel._walmart_import_order("PO-CANCEL")
        self.assertFalse(result)
        orders = self.env["sale.order"].search([("client_order_ref", "=", "PO-CANCEL")])
        self.assertFalse(orders)

    def test_country_code_is_mapped_to_iso2(self):
        payload = self.channel._walmart_order_to_payload("PO-X", _order(country="USA"))
        self.assertEqual(payload["address_shipping"]["country_code"], "US")
        payload_ca = self.channel._walmart_order_to_payload(
            "PO-Y", _order(country="CAN")
        )
        self.assertEqual(payload_ca["address_shipping"]["country_code"], "CA")

    def test_poll_enqueues_one_job_per_order(self):
        list_resp = {
            "list": {
                "meta": {},
                "elements": {
                    "order": [
                        {"purchaseOrderId": "PO-10"},
                        {"purchaseOrderId": "PO-11"},
                    ]
                },
            }
        }
        with (
            trap_jobs() as trap,
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", return_value=list_resp),
        ):
            self.channel._walmart_import_orders()
            trap.assert_jobs_count(2)
        # Cursor advances so the next poll is incremental.
        self.assertTrue(self.channel.walmart_last_import_date)

    def test_poll_paginates_on_next_cursor(self):
        page1 = {
            "list": {
                "meta": {"nextCursor": "?limit=1&soIndex=1"},
                "elements": {"order": [{"purchaseOrderId": "PO-20"}]},
            }
        }
        page2 = {
            "list": {
                "meta": {},
                "elements": {"order": [{"purchaseOrderId": "PO-21"}]},
            }
        }
        with (
            trap_jobs() as trap,
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", side_effect=[page1, page2]) as req,
        ):
            self.channel._walmart_import_orders()
            trap.assert_jobs_count(2)
        self.assertEqual(req.call_count, 2)
        # Second call must carry the nextCursor querystring on the path.
        self.assertIn("?limit=1", req.call_args_list[1].args[1])

    def test_cron_enqueues_one_job_per_channel(self):
        with trap_jobs() as trap:
            self.env["sale.channel"]._cron_walmart_import_orders()
            trap.assert_jobs_count(1)
