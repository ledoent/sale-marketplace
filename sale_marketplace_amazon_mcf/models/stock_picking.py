# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    amz_fulfillment_order_ids = fields.One2many(
        "sale.channel.fulfillment.order", "picking_id"
    )
    amz_mcf_count = fields.Integer(compute="_compute_amz_mcf_count")

    @api.depends("amz_fulfillment_order_ids")
    def _compute_amz_mcf_count(self):
        for picking in self:
            picking.amz_mcf_count = len(picking.amz_fulfillment_order_ids)

    def action_amz_mcf_fulfill(self):
        """Build a draft MCF fulfillment order from this delivery's moves.

        Each product is matched to an Amazon seller SKU via its FBA inventory
        record; duplicate SKUs are aggregated. Raises if any product has no FBA
        SKU (it cannot be fulfilled from Amazon stock).
        """
        self.ensure_one()
        fba_model = self.env["sale.channel.fba.inventory"]
        channels = self.env["sale.channel"]
        lines = {}
        for move in self.move_ids:
            fba = fba_model.search([("product_id", "=", move.product_id.id)], limit=1)
            if not fba:
                raise UserError(
                    _("No Amazon FBA SKU found for product %s.")
                    % move.product_id.display_name
                )
            channels |= fba.sale_channel_id
            entry = lines.setdefault(
                fba.seller_sku, {"product": move.product_id, "qty": 0.0}
            )
            entry["qty"] += move.product_uom_qty
        if not lines or not channels:
            raise UserError(_("Nothing to fulfill via Amazon MCF."))
        if len(channels) > 1:
            raise UserError(
                _(
                    "This delivery mixes products from multiple Amazon channels; "
                    "split it to fulfill via MCF."
                )
            )
        channel = channels
        reference = self.sale_id.name or self.name
        order = self.env["sale.channel.fulfillment.order"].create(
            {
                "name": reference,
                "sale_channel_id": channel.id,
                "picking_id": self.id,
                "partner_id": self.partner_id.id,
                "shipping_speed": channel.mcf_default_speed,
                "displayable_order_id": reference,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": data["product"].id,
                            "seller_sku": sku,
                            "item_id": sku,
                            "quantity": data["qty"],
                        },
                    )
                    for sku, data in lines.items()
                ],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.channel.fulfillment.order",
            "res_id": order.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_amz_mcf(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.channel.fulfillment.order",
            "view_mode": "list,form",
            "domain": [("picking_id", "=", self.id)],
        }
