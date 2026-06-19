# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    pricing_mode = fields.Selection(
        [
            ("manual", "Manual"),
            ("pricelist", "Pricelist"),
            ("competitive", "Competitive"),
        ],
        default="manual",
        help="How the target price pushed to Amazon is computed.",
    )
    pricing_pricelist_id = fields.Many2one("product.pricelist")
    competitive_rule = fields.Selection(
        [
            ("match_buy_box", "Match Buy Box"),
            ("undercut", "Undercut Buy Box"),
            ("floor_cost_plus", "Cost + Margin Floor"),
        ],
        default="match_buy_box",
    )
    competitive_undercut_pct = fields.Float(
        "Undercut %", default=1.0, help="Percent to undercut the buy box by."
    )
    competitive_floor_margin_pct = fields.Float(
        "Floor Margin %",
        default=10.0,
        help="Minimum net margin as a percent of price (margin-on-revenue); every "
        "computed price is clamped to the floor that clears this margin.",
    )
    price_push_enabled = fields.Boolean(default=False)
    last_price_sync_date = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # Price computation
    # ------------------------------------------------------------------
    def _amazon_price_floor(self, binding):
        """Price floor that clears the target NET margin (margin-on-revenue).

        Returns the price at which (price - cost) / price equals the configured
        floor margin. 0.0 when cost is unknown or the target margin is >= 100%
        (unachievable). The fees module extends this with a fee-aware floor that
        uses the same margin-on-revenue convention.
        """
        self.ensure_one()
        cost = binding.product_id.standard_price or 0.0
        margin = self.competitive_floor_margin_pct / 100.0
        if not cost or margin >= 1.0:
            return 0.0
        return cost / (1.0 - margin)

    def _amazon_compute_competitive_price(self, binding):
        """Target price for the competitive pricing mode, clamped to the floor."""
        self.ensure_one()
        floor = self._amazon_price_floor(binding)
        buy_box = binding.buy_box_price or 0.0
        rule = self.competitive_rule
        if rule == "floor_cost_plus":
            # Price at cost + target margin (NOT the buy box).
            target = floor
        elif rule == "undercut":
            target = buy_box * (1.0 - self.competitive_undercut_pct / 100.0)
        else:  # match_buy_box
            target = buy_box
        if floor:
            target = max(target, floor)
        return target

    def _amazon_compute_listing_price(self, binding):
        """Target price for a binding based on the channel's pricing mode."""
        self.ensure_one()
        if self.pricing_mode == "pricelist" and self.pricing_pricelist_id:
            return self.pricing_pricelist_id._get_product_price(binding.product_id, 1.0)
        if self.pricing_mode == "competitive":
            return self._amazon_compute_competitive_price(binding)
        # manual: leave the price as-is (never auto-push a change)
        return binding.current_list_price

    # ------------------------------------------------------------------
    # Price push
    # ------------------------------------------------------------------
    def _amazon_patch_listing_price(self, api, binding, price):
        self.ensure_one()
        currency = binding.product_id.currency_id.name or "USD"
        body = {
            "productType": "PRODUCT",
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/purchasable_offer",
                    "value": [
                        {
                            "marketplace_id": self.amazon_marketplace_id,
                            "currency": currency,
                            "our_price": [{"schedule": [{"value_with_tax": price}]}],
                        }
                    ],
                }
            ],
        }
        return api.patch_listings_item(
            sellerId=self.amazon_seller_id,
            sku=binding.external_id,
            marketplaceIds=[self.amazon_marketplace_id],
            body=body,
        )

    def _amazon_push_prices(self, trigger="manual"):
        """Push the computed target price for each active binding to Amazon."""
        self.ensure_one()
        from sp_api.api import ListingsItems

        api = self._amazon_get_api(ListingsItems)
        bindings = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.id), ("active", "=", True)]
        )
        rule = self.competitive_rule if self.pricing_mode == "competitive" else False
        pushed = 0
        for binding in bindings:
            target = self._amazon_compute_listing_price(binding)
            if not target:
                continue
            if (
                float_compare(target, binding.current_list_price, precision_digits=2)
                == 0
            ):
                continue
            try:
                self._amazon_patch_listing_price(api, binding, target)
            except Exception as exc:  # pragma: no cover - logged and skipped
                _logger.warning(
                    "Amazon price push failed for SKU %s: %s",
                    binding.external_id,
                    exc,
                )
                continue
            old_price = binding.current_list_price
            binding.current_list_price = target
            binding._log_price_change(old_price, target, trigger, rule)
            pushed += 1
        self.last_price_sync_date = fields.Datetime.now()
        return pushed

    # ------------------------------------------------------------------
    # Competitive sync
    # ------------------------------------------------------------------
    def _amazon_sync_competitive_prices(self):
        """Pull buy-box prices for active ASINs and update each binding."""
        self.ensure_one()
        from sp_api.api import Products

        api = self._amazon_get_api(Products)
        bindings = self.env["sale.channel.product"].search(
            [
                ("sale_channel_id", "=", self.id),
                ("active", "=", True),
                ("asin", "!=", False),
            ]
        )
        by_asin = {b.asin: b for b in bindings}
        asins = list(by_asin.keys())
        updated = 0
        for start in range(0, len(asins), 20):
            batch = asins[start : start + 20]
            try:
                result = api.get_competitive_pricing_for_asins(
                    asin_list=batch, marketplace_id=self.amazon_marketplace_id
                )
            except Exception as exc:  # pragma: no cover - logged and skipped
                _logger.warning(
                    "Amazon competitive pricing failed for %s: %s", batch, exc
                )
                continue
            for entry in result.payload or []:
                if entry.get("status") != "Success":
                    continue
                product = entry.get("Product", {})
                asin = (
                    product.get("Identifiers", {})
                    .get("MarketplaceASIN", {})
                    .get("ASIN")
                )
                binding = by_asin.get(asin)
                prices = product.get("CompetitivePricing", {}).get(
                    "CompetitivePrices", []
                )
                buy_box = next(
                    (p for p in prices if p.get("CompetitivePriceId") == "1"), None
                )
                if not binding or not buy_box:
                    continue
                amount = float(
                    buy_box.get("Price", {}).get("ListingPrice", {}).get("Amount", 0.0)
                    or 0.0
                )
                binding.write(
                    {
                        "buy_box_price": amount,
                        "buy_box_winner": bool(
                            buy_box.get("belongsToRequester", False)
                        ),
                    }
                )
                updated += 1  # per-binding, not per-batch
        self.last_price_sync_date = fields.Datetime.now()
        return updated

    # ------------------------------------------------------------------
    # Orchestration: actions + cron
    # ------------------------------------------------------------------
    def _amazon_do_sync_prices(self):
        self.ensure_one()
        if self.pricing_mode == "competitive":
            self._amazon_sync_competitive_prices()
        if self.price_push_enabled:
            self._amazon_push_prices(trigger="cron")

    def action_amazon_push_prices(self):
        self.ensure_one()
        if not self.amazon_seller_id:
            from odoo.exceptions import UserError

            raise UserError(_("Amazon Seller ID is required to push prices."))
        self.with_delay()._amazon_push_prices(trigger="manual")
        return True

    def action_amazon_sync_competitive_prices(self):
        self.ensure_one()
        self.with_delay()._amazon_sync_competitive_prices()
        return True

    @api.model
    def _cron_amazon_sync_prices(self):
        channels = self.search(
            [("channel_type", "=", "amazon"), ("price_push_enabled", "=", True)]
        )
        for channel in channels:
            channel._amazon_do_sync_prices()
