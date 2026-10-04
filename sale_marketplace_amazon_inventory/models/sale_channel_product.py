# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelProduct(models.Model):
    _inherit = "sale.channel.product"

    inventory_sync_enabled = fields.Boolean("Inventory Sync", default=True)
    last_pushed_qty = fields.Integer(default=-1, readonly=True, copy=False)
    last_inventory_push_date = fields.Datetime(
        "Last Inventory Push", readonly=True, copy=False
    )
