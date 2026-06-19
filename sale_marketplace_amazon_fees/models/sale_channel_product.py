# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SaleChannelProduct(models.Model):
    _inherit = "sale.channel.product"

    is_fba = fields.Boolean(
        "Fulfilled by Amazon",
        help="Estimate FBA fulfillment fees rather than merchant-fulfilled.",
    )
    referral_fee = fields.Float()
    fulfillment_fee = fields.Float()
    variable_closing_fee = fields.Float()
    other_fees = fields.Float()
    fee_basis_price = fields.Float(
        help="The price the latest fee estimate was based on."
    )
    total_fees = fields.Float(compute="_compute_total_fees", store=True)
    est_net_proceeds = fields.Float(
        "Estimated Net Proceeds", compute="_compute_margin", store=True
    )
    est_net_margin = fields.Float(
        "Estimated Net Margin", compute="_compute_margin", store=True
    )
    est_margin_pct = fields.Float(
        "Estimated Margin %", compute="_compute_margin", store=True
    )
    below_target_margin = fields.Boolean(
        compute="_compute_below_target_margin", store=True
    )

    @api.depends(
        "referral_fee", "fulfillment_fee", "variable_closing_fee", "other_fees"
    )
    def _compute_total_fees(self):
        for binding in self:
            binding.total_fees = (
                binding.referral_fee
                + binding.fulfillment_fee
                + binding.variable_closing_fee
                + binding.other_fees
            )

    @api.depends("fee_basis_price", "total_fees", "product_id.standard_price")
    def _compute_margin(self):
        for binding in self:
            cost = binding.product_id.standard_price or 0.0
            binding.est_net_proceeds = binding.fee_basis_price - binding.total_fees
            binding.est_net_margin = binding.est_net_proceeds - cost
            binding.est_margin_pct = (
                (binding.est_net_margin / binding.fee_basis_price * 100.0)
                if binding.fee_basis_price
                else 0.0
            )

    @api.depends(
        "est_margin_pct",
        "fee_basis_price",
        "sale_channel_id.competitive_floor_margin_pct",
    )
    def _compute_below_target_margin(self):
        for binding in self:
            target = binding.sale_channel_id.competitive_floor_margin_pct
            binding.below_target_margin = bool(binding.fee_basis_price) and (
                binding.est_margin_pct < target
            )
