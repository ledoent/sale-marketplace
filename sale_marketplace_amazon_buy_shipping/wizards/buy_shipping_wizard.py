# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import binascii

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BuyShippingWizard(models.TransientModel):
    _name = "sale.channel.buy.shipping.wizard"
    _description = "Buy Amazon Shipping Wizard"

    picking_id = fields.Many2one("stock.picking", required=True)
    sale_channel_id = fields.Many2one(
        "sale.channel", compute="_compute_sale_channel_id"
    )
    weight = fields.Float(default=1.0, help="Package weight in ounces.")
    rate_line_ids = fields.One2many(
        "sale.channel.buy.shipping.rate", "wizard_id", string="Rates"
    )

    @api.depends("picking_id")
    def _compute_sale_channel_id(self):
        for wizard in self:
            wizard.sale_channel_id = wizard.picking_id._amazon_channel()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        picking = self.env["stock.picking"].browse(vals.get("picking_id"))
        if picking:
            weight = sum(
                (move.product_id.weight or 0.0) * move.product_uom_qty
                for move in picking.move_ids
            )
            vals["weight"] = weight or 1.0
        return vals

    def _reload(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_get_rates(self):
        self.ensure_one()
        channel = self.sale_channel_id
        if not channel:
            raise UserError(_("This delivery is not linked to an Amazon channel."))
        rates = channel._amazon_get_shipping_rates(self.picking_id, self.weight)
        self.rate_line_ids.unlink()
        self.env["sale.channel.buy.shipping.rate"].create(
            [dict(rate, wizard_id=self.id) for rate in rates]
        )
        return self._reload()

    def _purchase(self, rate):
        """Buy the label and persist tracking + shipment atomically.

        Validates the label base64 before writing anything, and performs the
        shipment create + picking write in the same transaction so a failure
        can never leave an orphaned shipment record.
        """
        self.ensure_one()
        channel = self.sale_channel_id
        res = channel._amazon_purchase_label(
            self.picking_id, rate.service_id, rate.service_offer_id, self.weight
        )
        contents = res.get("label_contents")
        if not contents:
            raise UserError(_("Amazon returned no shipping label."))
        try:
            base64.b64decode(contents, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UserError(_("Amazon returned an invalid label.")) from exc

        currency = self.env["res.currency"].search(
            [("name", "=", (res.get("currency") or "USD"))], limit=1
        )
        attachment = self.env["ir.attachment"].create(
            {
                "name": f"amazon-label-{self.picking_id.name}.pdf",
                "type": "binary",
                "datas": contents,
                "res_model": "stock.picking",
                "res_id": self.picking_id.id,
            }
        )
        shipment = self.env["sale.channel.shipment"].create(
            {
                "sale_channel_id": channel.id,
                "picking_id": self.picking_id.id,
                "amazon_shipment_id": res.get("amazon_shipment_id"),
                "tracking_number": res.get("tracking_number"),
                "carrier_name": res.get("carrier_name"),
                "service_name": res.get("service_name"),
                "cost": res.get("cost") or 0.0,
                "currency_id": currency.id or False,
                "label_attachment_id": attachment.id,
            }
        )
        self.picking_id.write(
            {
                "carrier_tracking_ref": res.get("tracking_number"),
                "amazon_label_purchased": True,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.channel.shipment",
            "res_id": shipment.id,
            "view_mode": "form",
            "target": "current",
        }


class BuyShippingRate(models.TransientModel):
    _name = "sale.channel.buy.shipping.rate"
    _description = "Buy Amazon Shipping Rate Option"

    wizard_id = fields.Many2one(
        "sale.channel.buy.shipping.wizard", required=True, ondelete="cascade"
    )
    service_id = fields.Char()
    service_offer_id = fields.Char()
    carrier_name = fields.Char()
    service_name = fields.Char()
    amount = fields.Float()
    currency = fields.Char()

    def action_buy(self):
        self.ensure_one()
        return self.wizard_id._purchase(self)
