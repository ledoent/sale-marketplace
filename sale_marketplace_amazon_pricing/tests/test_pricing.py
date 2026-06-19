# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_pricing.models.sale_channel"


def _competitive_payload(asin, amount, mine=False):
    return [
        {
            "status": "Success",
            "Product": {
                "Identifiers": {"MarketplaceASIN": {"ASIN": asin}},
                "CompetitivePricing": {
                    "CompetitivePrices": [
                        {
                            "CompetitivePriceId": "1",
                            "belongsToRequester": mine,
                            "Price": {"ListingPrice": {"Amount": amount}},
                        }
                    ]
                },
            },
        }
    ]


class TestPricing(TransactionCase):
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
                "pricing_mode": "competitive",
                "competitive_rule": "match_buy_box",
                "competitive_floor_margin_pct": 10.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1", "standard_price": 10.0}
        )
        cls.binding = cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
                "asin": "ASIN1",
            }
        )

    # ---- competitive price computation (incl. the floor_cost_plus fix) ----
    def test_compute_match_buy_box(self):
        self.binding.buy_box_price = 20.0
        self.assertEqual(
            self.channel._amazon_compute_competitive_price(self.binding), 20.0
        )

    def test_compute_undercut(self):
        self.channel.write(
            {"competitive_rule": "undercut", "competitive_undercut_pct": 5.0}
        )
        self.binding.buy_box_price = 20.0
        self.assertEqual(
            self.channel._amazon_compute_competitive_price(self.binding), 19.0
        )

    def test_compute_floor_cost_plus_uses_cost_not_buy_box(self):
        # cost 10 + 20% margin = 12; the buy box (20) must be ignored.
        self.channel.write(
            {
                "competitive_rule": "floor_cost_plus",
                "competitive_floor_margin_pct": 20.0,
            }
        )
        self.binding.buy_box_price = 20.0
        self.assertAlmostEqual(
            self.channel._amazon_compute_competitive_price(self.binding), 12.0
        )

    def test_compute_clamps_to_floor(self):
        # undercut would drop below the cost+margin floor (11); clamp to 11.
        self.channel.write(
            {"competitive_rule": "undercut", "competitive_undercut_pct": 50.0}
        )
        self.binding.buy_box_price = 10.0
        self.assertAlmostEqual(
            self.channel._amazon_compute_competitive_price(self.binding), 11.0
        )

    # ---- price push + history ----
    def test_push_pushes_and_logs_history(self):
        self.binding.buy_box_price = 20.0
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            pushed = self.channel._amazon_push_prices()
        self.assertEqual(pushed, 1)
        self.assertEqual(api.patch_listings_item.call_count, 1)
        _, kwargs = api.patch_listings_item.call_args
        self.assertEqual(kwargs["sku"], "SKU-1")
        self.assertEqual(self.binding.current_list_price, 20.0)
        self.assertTrue(self.channel.last_price_sync_date)
        self.assertEqual(len(self.binding.price_history_ids), 1)
        self.assertEqual(self.binding.price_history_ids.new_price, 20.0)

    def test_push_skips_unchanged(self):
        self.binding.write({"buy_box_price": 20.0, "current_list_price": 20.0})
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            pushed = self.channel._amazon_push_prices()
        self.assertEqual(pushed, 0)
        api.patch_listings_item.assert_not_called()

    @mute_logger(_MODEL_PATH)
    def test_push_error_isolation_counts_per_listing(self):
        # two SKUs; the first API call fails, the second succeeds.
        product2 = self.env["product.product"].create(
            {"name": "Widget2", "default_code": "SKU-2", "standard_price": 10.0}
        )
        self.env["sale.channel.product"].create(
            {
                "sale_channel_id": self.channel.id,
                "product_id": product2.id,
                "external_id": "SKU-2",
                "asin": "ASIN2",
                "buy_box_price": 30.0,
            }
        )
        self.binding.buy_box_price = 20.0
        api = MagicMock()
        api.patch_listings_item.side_effect = [Exception("boom"), MagicMock()]
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            pushed = self.channel._amazon_push_prices()
        # exactly one succeeded -> counter is per-listing, not per-batch
        self.assertEqual(pushed, 1)
        self.assertEqual(api.patch_listings_item.call_count, 2)

    # ---- competitive sync ----
    def test_sync_competitive_updates_buy_box(self):
        api = MagicMock()
        api.get_competitive_pricing_for_asins.return_value.payload = (
            _competitive_payload("ASIN1", 25.0, mine=True)
        )
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            updated = self.channel._amazon_sync_competitive_prices()
        self.assertEqual(updated, 1)
        self.assertEqual(self.binding.buy_box_price, 25.0)
        self.assertTrue(self.binding.buy_box_winner)

    def test_sync_competitive_batches_by_20(self):
        for i in range(2, 26):  # 24 more bindings -> 25 total -> 2 batches
            p = self.env["product.product"].create(
                {"name": f"W{i}", "default_code": f"SKU-{i}"}
            )
            self.env["sale.channel.product"].create(
                {
                    "sale_channel_id": self.channel.id,
                    "product_id": p.id,
                    "external_id": f"SKU-{i}",
                    "asin": f"ASIN{i}",
                }
            )
        api = MagicMock()
        api.get_competitive_pricing_for_asins.return_value.payload = []
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_sync_competitive_prices()
        self.assertEqual(api.get_competitive_pricing_for_asins.call_count, 2)

    def test_sync_competitive_skips_no_asin(self):
        self.binding.asin = False
        api = MagicMock()
        api.get_competitive_pricing_for_asins.return_value.payload = []
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            updated = self.channel._amazon_sync_competitive_prices()
        self.assertEqual(updated, 0)
        api.get_competitive_pricing_for_asins.assert_not_called()

    # ---- cron entry point ----
    def test_cron_filters_price_push_enabled(self):
        self.channel.price_push_enabled = True
        self.binding.buy_box_price = 20.0
        api = MagicMock()
        api.get_competitive_pricing_for_asins.return_value.payload = (
            _competitive_payload("ASIN1", 22.0)
        )
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.env["sale.channel"]._cron_amazon_sync_prices()
        # competitive sync ran (buy box updated) and a push happened
        self.assertEqual(self.binding.buy_box_price, 22.0)
        self.assertTrue(api.patch_listings_item.called)

    def test_cron_skips_disabled_channel(self):
        self.channel.price_push_enabled = False
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.env["sale.channel"]._cron_amazon_sync_prices()
        api.patch_listings_item.assert_not_called()
