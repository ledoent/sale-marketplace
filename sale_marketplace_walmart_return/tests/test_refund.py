# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase

_BASE = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


def _order(order_qty="1", amount=100.0):
    return {
        "order": {
            "orderLines": {
                "orderLine": [
                    {
                        "lineNumber": "1",
                        "item": {"sku": "SKU-1"},
                        "orderLineQuantity": {
                            "unitOfMeasurement": "EACH",
                            "amount": order_qty,
                        },
                        "charges": {
                            "charge": [
                                {
                                    "chargeType": "PRODUCT",
                                    "chargeAmount": {
                                        "currency": "USD",
                                        "amount": amount,
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        }
    }


class TestRefund(TransactionCase):
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
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1"}
        )
        cls.ret = cls.env["sale.channel.walmart.return"].create(
            {
                "sale_channel_id": cls.channel.id,
                "return_order_id": "R-1",
                "purchase_order_id": "PO-1",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "seller_sku": "SKU-1",
                            "quantity": 1,
                            "return_reason": "Defective",
                        },
                    )
                ],
            }
        )

    def _fake_request(self, order=None):
        order = order or _order()

        def _request(method, path, params=None, payload=None, token=None):
            return order if method == "GET" else {}

        return _request

    def test_issue_refund_posts_and_stamps(self):
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", side_effect=self._fake_request()) as req,
        ):
            result = self.channel._walmart_issue_refund(self.ret)

        self.assertTrue(result)
        post_calls = [c for c in req.call_args_list if c.args[0] == "POST"]
        self.assertEqual(len(post_calls), 1)
        self.assertEqual(post_calls[0].args[1], "/v3/orders/PO-1/refund")
        refund = post_calls[0].kwargs["payload"]["orderRefund"]
        self.assertEqual(refund["purchaseOrderId"], "PO-1")
        line = refund["orderLines"]["orderLine"][0]
        self.assertEqual(line["lineNumber"], "1")
        charge = line["refunds"]["refund"][0]["refundCharges"]["refundCharge"][0]
        self.assertEqual(charge["charge"]["chargeAmount"]["amount"], 100.0)
        self.assertTrue(self.ret.walmart_refund_issued)
        self.assertTrue(self.ret.walmart_refund_id)

    def test_refund_prorated_for_partial_return(self):
        # return qty 1 against an order line of qty 2 -> half the product charge
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(
                f"{_BASE}._walmart_request",
                side_effect=self._fake_request(order=_order(order_qty="2")),
            ) as req,
        ):
            self.channel._walmart_issue_refund(self.ret)
        post = [c for c in req.call_args_list if c.args[0] == "POST"][0]
        charge = post.kwargs["payload"]["orderRefund"]["orderLines"]["orderLine"][0][
            "refunds"
        ]["refund"][0]["refundCharges"]["refundCharge"][0]
        self.assertEqual(charge["charge"]["chargeAmount"]["amount"], 50.0)

    def test_issue_refund_idempotent(self):
        self.ret.walmart_refund_issued = "2026-06-01 00:00:00"
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request") as req,
        ):
            result = self.channel._walmart_issue_refund(self.ret)
        self.assertFalse(result)
        req.assert_not_called()

    def test_action_button_issues_refund(self):
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", side_effect=self._fake_request()),
        ):
            self.ret.action_walmart_issue_refund()
        self.assertTrue(self.ret.walmart_refund_issued)

    def test_auto_refund_in_automation(self):
        self.channel.walmart_auto_refund = True
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", side_effect=self._fake_request()),
        ):
            self.channel._walmart_run_return_automation(self.ret)
        self.assertTrue(self.ret.walmart_refund_issued)
