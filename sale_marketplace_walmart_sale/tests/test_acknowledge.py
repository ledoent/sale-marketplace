# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase

from odoo.addons.queue_job.tests.common import trap_jobs

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


class TestAcknowledge(TransactionCase):
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
        cls.partner = cls.env["res.partner"].create({"name": "Buyer"})
        cls.product = cls.env["product.product"].create({"name": "Widget"})
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "sale_channel_id": cls.channel.id,
                "client_order_ref": "PO-1",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "product_uom_qty": 2,
                            "price_unit": 10.0,
                        },
                    )
                ],
            }
        )

    def _fake_request(self):
        def _request(method, path, params=None, payload=None, token=None):
            return _ORDER if method == "GET" else {}

        return _request

    def test_acknowledge_posts_and_stamps(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(
                f"{_MODEL}._walmart_request", side_effect=self._fake_request()
            ) as req,
        ):
            result = self.channel._walmart_acknowledge_order("PO-1", order=self.order)

        self.assertTrue(result)
        post_calls = [c for c in req.call_args_list if c.args[0] == "POST"]
        self.assertEqual(len(post_calls), 1)
        self.assertEqual(post_calls[0].args[1], "/v3/orders/PO-1/acknowledge")
        line = post_calls[0].kwargs["payload"]["orderAcknowledgement"]["orderLines"][
            "orderLine"
        ][0]
        status = line["orderLineStatuses"]["orderLineStatus"][0]
        self.assertEqual(line["lineNumber"], "1")
        self.assertEqual(status["status"], "Acknowledged")
        self.assertEqual(status["statusQuantity"]["amount"], "2")
        self.assertTrue(self.order.walmart_acknowledged)

    def test_acknowledge_stamps_via_lookup(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", side_effect=self._fake_request()),
        ):
            self.channel._walmart_acknowledge_order("PO-1")
        self.assertTrue(self.order.walmart_acknowledged)

    def test_cron_enqueues_unacknowledged(self):
        with trap_jobs() as trap:
            self.env["sale.channel"]._cron_walmart_acknowledge_orders()
            trap.assert_jobs_count(1)

    def test_cron_skips_acknowledged(self):
        self.order.walmart_acknowledged = fields.Datetime.now()
        with trap_jobs() as trap:
            self.env["sale.channel"]._cron_walmart_acknowledge_orders()
            trap.assert_jobs_count(0)

    def test_action_button_acknowledges(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", side_effect=self._fake_request()),
        ):
            self.order.action_walmart_acknowledge()
        self.assertTrue(self.order.walmart_acknowledged)
