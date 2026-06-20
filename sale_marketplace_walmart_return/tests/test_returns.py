# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

_BASE = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


def _returns(return_id="R-1", po="PO-1", qty=1, with_qty=True, next_cursor=None):
    line = {
        "item": {"sku": "SKU-1", "productName": "Widget"},
        "returnReason": "Defective",
    }
    if with_qty:
        line["returnQuantity"] = {"unitOfMeasurement": "EACH", "measurementValue": qty}
    return {
        "returnOrders": [
            {
                "returnOrderId": return_id,
                "customerOrderId": po,
                "returnOrderLines": [line],
            }
        ],
        "meta": {"nextCursor": next_cursor},
    }


@tagged("post_install", "-at_install")
class TestReturns(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
                "warehouse_id": cls.warehouse.id,
                "walmart_returns_enabled": True,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Widget",
                "default_code": "SKU-1",
                "is_storable": True,
                "invoice_policy": "order",
                "taxes_id": [(6, 0, [])],
                "property_account_income_id": cls.company_data[
                    "default_account_revenue"
                ].id,
            }
        )

    def _run(self, response=None):
        resp = response if response is not None else _returns()
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", return_value=resp),
        ):
            return self.channel._walmart_pull_returns()

    def _ret(self, return_id="R-1"):
        return self.env["sale.channel.walmart.return"].search(
            [
                ("sale_channel_id", "=", self.channel.id),
                ("return_order_id", "=", return_id),
            ]
        )

    def _make_invoiced_order(self, price=100.0):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "sale_channel_id": self.channel.id,
                "client_order_ref": "PO-1",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "price_unit": price,
                        },
                    )
                ],
            }
        )
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        return order, invoice

    def test_pull_creates_return(self):
        self._run()
        ret = self._ret()
        self.assertEqual(len(ret), 1)
        self.assertEqual(ret.purchase_order_id, "PO-1")
        self.assertEqual(ret.line_ids.product_id, self.product)
        self.assertEqual(ret.line_ids.quantity, 1)
        self.assertEqual(ret.line_ids.return_reason, "Defective")
        self.assertEqual(ret.state, "new")
        self.assertTrue(self.channel.walmart_last_return_sync_date)

    def test_auto_restock_picking(self):
        self.channel.walmart_auto_return_picking = True
        self._run()
        ret = self._ret()
        self.assertTrue(ret.return_picking_id)
        self.assertEqual(ret.return_picking_id.origin, "R-1")
        self.assertEqual(ret.state, "picking_created")

    def test_auto_credit_note(self):
        self._make_invoiced_order(price=100.0)
        self.channel.walmart_auto_credit_note = True
        self._run()
        ret = self._ret()
        self.assertTrue(ret.credit_note_id)
        self.assertEqual(ret.credit_note_id.move_type, "out_refund")
        self.assertEqual(ret.credit_note_id.state, "posted")
        self.assertEqual(ret.state, "credited")

    def test_both_automations_done(self):
        self._make_invoiced_order(price=100.0)
        self.channel.write(
            {
                "walmart_auto_return_picking": True,
                "walmart_auto_credit_note": True,
            }
        )
        self._run()
        self.assertEqual(self._ret().state, "done")

    def test_idempotent_pull(self):
        self._run()
        self._run()
        self.assertEqual(len(self._ret()), 1)

    def test_missing_quantity_is_zero(self):
        self.channel.walmart_auto_return_picking = True
        self._run(response=_returns(with_qty=False))
        ret = self._ret()
        self.assertEqual(ret.line_ids.quantity, 0.0)
        # qty 0 -> no restock move -> picking not created
        self.assertFalse(ret.return_picking_id)
        self.assertEqual(ret.state, "new")

    def test_pagination(self):
        page1 = _returns(return_id="R-1", next_cursor="?cursor=2")
        page2 = _returns(return_id="R-2")
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", side_effect=[page1, page2]) as req,
        ):
            processed = self.channel._walmart_pull_returns()
        self.assertEqual(processed, 2)
        self.assertEqual(req.call_count, 2)
        self.assertIn("?cursor=2", req.call_args_list[1].args[1])
        self.assertEqual(
            set(
                self.env["sale.channel.walmart.return"]
                .search([("sale_channel_id", "=", self.channel.id)])
                .mapped("return_order_id")
            ),
            {"R-1", "R-2"},
        )

    def test_cursor_not_advanced_on_empty_pull(self):
        # a pull that returns nothing must not advance the cursor (else returns
        # created in the window would be skipped on the next run)
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(
                f"{_BASE}._walmart_request",
                return_value={"returnOrders": [], "meta": {}},
            ),
        ):
            self.channel._walmart_pull_returns()
        self.assertFalse(self.channel.walmart_last_return_sync_date)

    @mute_logger("odoo.addons.sale_marketplace_walmart_return.models.sale_channel")
    def test_automation_isolates_credit_note_failure(self):
        # if the credit note raises, the restock picking is still created and the
        # return state reflects what actually succeeded (no exception propagates)
        self._make_invoiced_order(price=100.0)
        self.channel.write(
            {
                "walmart_auto_return_picking": True,
                "walmart_auto_credit_note": True,
            }
        )
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", return_value=_returns()),
            patch.object(
                type(self.channel),
                "_walmart_create_credit_note",
                side_effect=Exception("boom"),
            ),
        ):
            self.channel._walmart_pull_returns()
        ret = self._ret()
        self.assertTrue(ret.return_picking_id)
        self.assertFalse(ret.credit_note_id)
        self.assertEqual(ret.state, "picking_created")
