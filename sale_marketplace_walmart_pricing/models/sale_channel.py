# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    walmart_pricing_mode = fields.Selection(
        [
            ("manual", "Manual"),
            ("pricelist", "Pricelist"),
        ],
        default="manual",
        help="How the target price pushed to Walmart is computed.",
    )
    walmart_pricing_pricelist_id = fields.Many2one("product.pricelist")
    walmart_floor_margin_pct = fields.Float(
        "Walmart Floor Margin %",
        default=10.0,
        help="Minimum net margin as a percent of price (margin-on-revenue); every "
        "computed price is clamped to the floor that clears this margin.",
    )
    walmart_price_push_enabled = fields.Boolean(default=False)
    walmart_last_price_sync_date = fields.Datetime(readonly=True)

    def _walmart_price_floor(self, binding):
        """Price floor that clears the target NET margin (margin-on-revenue).

        Returns the price at which (price - cost) / price equals the configured
        floor margin. 0.0 when cost is unknown or the target margin is >= 100%
        (unachievable).
        """
        self.ensure_one()
        cost = binding.product_id.standard_price or 0.0
        margin = self.walmart_floor_margin_pct / 100.0
        if not cost or margin >= 1.0:
            return 0.0
        return cost / (1.0 - margin)

    def _walmart_compute_listing_price(self, binding):
        """Target price for a binding based on the channel's pricing mode."""
        self.ensure_one()
        if (
            self.walmart_pricing_mode == "pricelist"
            and self.walmart_pricing_pricelist_id
        ):
            target = self.walmart_pricing_pricelist_id._get_product_price(
                binding.product_id, 1.0
            )
        else:
            # manual: leave the price as-is (never auto-push a change)
            target = binding.walmart_list_price
        floor = self._walmart_price_floor(binding)
        if floor:
            target = max(target, floor)
        return target

    def _walmart_patch_listing_price(self, binding, price, token=None):
        self.ensure_one()
        currency = binding.product_id.currency_id.name or "USD"
        payload = {
            "sku": binding.external_id,
            "pricing": [
                {
                    "currentPriceType": "BASE",
                    "currentPrice": {"currency": currency, "amount": price},
                }
            ],
        }
        return self._walmart_request("PUT", "/v3/price", payload=payload, token=token)

    def _walmart_push_prices(self, trigger="manual"):
        """Push the computed target price for each active binding to Walmart."""
        self.ensure_one()
        token = self._walmart_get_token()
        bindings = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.id), ("active", "=", True)]
        )
        pushed = 0
        for binding in bindings:
            target = self._walmart_compute_listing_price(binding)
            if not target:
                continue
            if (
                float_compare(target, binding.walmart_list_price, precision_digits=2)
                == 0
            ):
                continue
            try:
                self._walmart_patch_listing_price(binding, target, token=token)
            except Exception as exc:
                _logger.warning(
                    "Walmart price push failed for SKU %s: %s",
                    binding.external_id,
                    exc,
                )
                continue
            old_price = binding.walmart_list_price
            binding.walmart_list_price = target
            binding._walmart_log_price_change(old_price, target, trigger)
            pushed += 1
        self.walmart_last_price_sync_date = fields.Datetime.now()
        self._walmart_log("price_push", f"Pushed {pushed} price change(s).")
        return pushed

    def action_walmart_push_prices(self):
        self.ensure_one()
        self.with_delay(
            description=f"Push Walmart prices for {self.display_name}"
        )._walmart_push_prices(trigger="manual")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Price Push Queued"),
                "message": _("Price synchronisation job has been queued."),
                "type": "info",
            },
        }

    @api.model
    def _cron_walmart_push_prices(self):
        channels = self.search(
            [
                ("channel_type", "=", "walmart"),
                ("active", "=", True),
                ("walmart_price_push_enabled", "=", True),
            ]
        )
        for channel in channels:
            channel.with_delay(
                description=f"Push Walmart prices for {channel.display_name}"
            )._walmart_push_prices(trigger="cron")
