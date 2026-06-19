# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SaleChannelFbaInventory(models.Model):
    _name = "sale.channel.fba.inventory"
    _description = "Sale Channel FBA Inventory"
    _order = "seller_sku"
    _sql_constraints = [
        (
            "channel_sku_uniq",
            "unique(sale_channel_id, seller_sku)",
            "FBA inventory is unique per channel and SKU.",
        ),
    ]

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    seller_sku = fields.Char(required=True, index=True)
    product_id = fields.Many2one("product.product")
    fulfillable_qty = fields.Integer()
    inbound_qty = fields.Integer()
    reserved_qty = fields.Integer()
    unsellable_qty = fields.Integer()
    total_qty = fields.Integer()
    odoo_qty = fields.Integer(
        "Odoo On-hand", help="Odoo on-hand at the channel warehouse at last sync."
    )
    drift = fields.Integer(
        compute="_compute_drift",
        store=True,
        help="Amazon fulfillable minus Odoo on-hand.",
    )
    last_sync_date = fields.Datetime(readonly=True)

    @api.depends("fulfillable_qty", "odoo_qty")
    def _compute_drift(self):
        for record in self:
            record.drift = record.fulfillable_qty - record.odoo_qty
