# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelShipment(models.Model):
    _name = "sale.channel.shipment"
    _description = "Sale Channel Shipment (purchased label)"
    _order = "create_date desc, id desc"

    sale_channel_id = fields.Many2one("sale.channel", required=True, ondelete="cascade")
    picking_id = fields.Many2one("stock.picking", ondelete="set null")
    amazon_shipment_id = fields.Char()
    tracking_number = fields.Char()
    carrier_name = fields.Char()
    service_name = fields.Char()
    cost = fields.Float()
    currency_id = fields.Many2one("res.currency")
    label_attachment_id = fields.Many2one("ir.attachment", string="Label")

    def action_download_label(self):
        self.ensure_one()
        if not self.label_attachment_id:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.label_attachment_id.id}?download=true",
            "target": "self",
        }
