# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


class TestPricing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
                "walmart_floor_margin_pct": 20.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "standard_price": 80.0}
        )
        cls.binding = cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
                "walmart_list_price": 50.0,
            }
        )

    def test_price_floor_margin_on_revenue(self):
        # cost 80, 20% margin-on-revenue -> 80 / (1 - 0.20) = 100.0
        self.assertAlmostEqual(self.channel._walmart_price_floor(self.binding), 100.0)

    def test_price_floor_zero_without_cost(self):
        self.product.standard_price = 0.0
        self.assertEqual(self.channel._walmart_price_floor(self.binding), 0.0)

    def test_price_floor_zero_when_margin_unachievable(self):
        self.channel.walmart_floor_margin_pct = 100.0
        self.assertEqual(self.channel._walmart_price_floor(self.binding), 0.0)

    def test_compute_manual_clamps_to_floor(self):
        # manual target is the current list price (50), clamped up to floor 100.
        self.assertAlmostEqual(
            self.channel._walmart_compute_listing_price(self.binding), 100.0
        )

    def test_compute_pricelist_mode(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "WM",
                "item_ids": [
                    (
                        0,
                        0,
                        {
                            "applied_on": "3_global",
                            "compute_price": "fixed",
                            "fixed_price": 150.0,
                        },
                    )
                ],
            }
        )
        self.channel.write(
            {
                "walmart_pricing_mode": "pricelist",
                "walmart_pricing_pricelist_id": pricelist.id,
            }
        )
        self.assertAlmostEqual(
            self.channel._walmart_compute_listing_price(self.binding), 150.0
        )

    def test_push_sends_changed_price_and_logs(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request") as req,
        ):
            pushed = self.channel._walmart_push_prices(trigger="manual")
        self.assertEqual(pushed, 1)
        _, kwargs = req.call_args
        amount = kwargs["payload"]["pricing"][0]["currentPrice"]["amount"]
        self.assertAlmostEqual(amount, 100.0)
        self.assertAlmostEqual(self.binding.walmart_list_price, 100.0)
        history = self.binding.walmart_price_history_ids
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history.old_price, 50.0)
        self.assertAlmostEqual(history.new_price, 100.0)

    def test_push_skips_unchanged(self):
        self.binding.walmart_list_price = 100.0  # already at the floor target
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request") as req,
        ):
            pushed = self.channel._walmart_push_prices()
        self.assertEqual(pushed, 0)
        req.assert_not_called()

    @mute_logger("odoo.addons.sale_marketplace_walmart_pricing.models.sale_channel")
    def test_push_error_isolated(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", side_effect=Exception("boom")),
        ):
            pushed = self.channel._walmart_push_prices()
        self.assertEqual(pushed, 0)
        # Price not advanced and no history logged on failure.
        self.assertAlmostEqual(self.binding.walmart_list_price, 50.0)
        self.assertFalse(self.binding.walmart_price_history_ids)
        self.assertTrue(self.channel.walmart_last_price_sync_date)
