# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# SP-API FeeType values bucketed into our fixed-fee categories.
_FULFILLMENT_FEE_TYPES = {"FBAFees", "FulfillmentFees", "FBAPerUnitFulfillmentFee"}


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    last_fee_sync_date = fields.Datetime(readonly=True)

    @api.model
    def _amazon_parse_fee_estimate(self, payload):
        """Map a GetMyFeesEstimate payload to binding fee values.

        Returns None when the estimate was not successful, so the caller leaves
        the listing's existing fee data untouched.
        """
        result = (payload or {}).get("FeesEstimateResult", {})
        if result.get("Status") != "Success":
            return None
        estimate = result.get("FeesEstimate", {})
        basis = float(
            estimate.get("FeesEstimateIdentifier", {})
            .get("PriceToEstimateFees", {})
            .get("ListingPrice", {})
            .get("Amount", 0.0)
            or 0.0
        )
        vals = {
            "referral_fee": 0.0,
            "fulfillment_fee": 0.0,
            "variable_closing_fee": 0.0,
            "other_fees": 0.0,
            "fee_basis_price": basis,
        }
        for detail in estimate.get("FeeDetailList", []):
            amount = float(detail.get("FeeAmount", {}).get("Amount", 0.0) or 0.0)
            fee_type = detail.get("FeeType")
            if fee_type == "ReferralFee":
                vals["referral_fee"] += amount
            elif fee_type in _FULFILLMENT_FEE_TYPES:
                vals["fulfillment_fee"] += amount
            elif fee_type == "VariableClosingFee":
                vals["variable_closing_fee"] += amount
            else:
                # Unknown fee types are still counted so the total is honest.
                vals["other_fees"] += amount
        return vals

    def _amazon_sync_fees(self):
        """Refresh fee estimates for active priced listings on this channel."""
        self.ensure_one()
        from sp_api.api import ProductFees

        api = self._amazon_get_api(ProductFees)
        bindings = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.id), ("active", "=", True)]
        )
        synced = 0
        for binding in bindings:
            price = binding.current_list_price or binding.buy_box_price
            if not price:
                continue
            try:
                result = api.get_product_fees_estimate_for_sku(
                    binding.external_id, price, is_fba=binding.is_fba
                )
            except Exception as exc:  # pragma: no cover - logged and skipped
                _logger.warning(
                    "Amazon fee estimate failed for SKU %s: %s",
                    binding.external_id,
                    exc,
                )
                continue
            vals = self._amazon_parse_fee_estimate(result.payload)
            if not vals:
                continue
            binding.write(vals)
            synced += 1
        self.last_fee_sync_date = fields.Datetime.now()
        return synced

    def _amazon_price_floor(self, binding):
        """Fee-aware price floor.

        Extends the pricing module's cost-plus-margin floor so that, after the
        referral percentage and fixed fees, the listing still clears the target
        margin. Falls back to the base floor when there is no fee data or when
        the referral + margin would consume the whole price (denom <= 0).
        """
        base = super()._amazon_price_floor(binding)
        cost = binding.product_id.standard_price or 0.0
        if not cost or not binding.fee_basis_price:
            return base
        referral_pct = binding.referral_fee / binding.fee_basis_price
        fixed_fees = (
            binding.fulfillment_fee + binding.variable_closing_fee + binding.other_fees
        )
        margin = self.competitive_floor_margin_pct / 100.0
        denom = 1.0 - referral_pct - margin
        if denom <= 0:
            return base
        fee_floor = (cost + fixed_fees) / denom
        return max(base, fee_floor)

    def action_amazon_sync_fees(self):
        self.ensure_one()
        self.with_delay()._amazon_sync_fees()
        return True

    @api.model
    def _cron_amazon_sync_fees(self):
        channels = self.search([("channel_type", "=", "amazon")])
        for channel in channels:
            channel._amazon_sync_fees()
