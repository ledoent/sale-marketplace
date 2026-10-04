# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import binascii
import gzip
import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BuyShippingWizard(models.TransientModel):
    _name = "sale.channel.buy.shipping.wizard"
    _description = "Buy Amazon Shipping Wizard"

    picking_id = fields.Many2one("stock.picking", required=True)
    sale_channel_id = fields.Many2one(
        "sale.channel", compute="_compute_sale_channel_id"
    )
    weight = fields.Float(
        default=1.0, help="Total packed weight in kilograms, including packaging."
    )
    package_length = fields.Float(help="Package length in centimeters.")
    package_width = fields.Float(help="Package width in centimeters.")
    package_height = fields.Float(help="Package height in centimeters.")
    quoted_request = fields.Text(readonly=True)
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
            weight_uom = self.env[
                "product.template"
            ]._get_weight_uom_id_from_ir_config_parameter()
            vals["weight"] = (
                weight_uom._compute_quantity(
                    weight, self.env.ref("uom.product_uom_kg"), round=False
                )
                or 1.0
            )
        return vals

    def _dimensions(self):
        return {
            "Length": self.package_length,
            "Width": self.package_width,
            "Height": self.package_height,
        }

    def _request_snapshot(self):
        return json.dumps(
            self.sale_channel_id._amazon_shipment_request(
                self.picking_id, self.weight, self._dimensions()
            ),
            sort_keys=True,
        )

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
        rates = channel._amazon_get_shipping_rates(
            self.picking_id, self.weight, self._dimensions()
        )
        self.quoted_request = self._request_snapshot()
        self.rate_line_ids.unlink()
        self.env["sale.channel.buy.shipping.rate"].create(
            [dict(rate, wizard_id=self.id) for rate in rates]
        )
        return self._reload()

    def _purchase(self, rate):
        """Buy a label, then persist the validated document and tracking locally.

        Amazon's purchase cannot be rolled back with the Odoo transaction.
        An ambiguous response requires checking Seller Central before retrying.
        """
        self.ensure_one()
        # Serialize successful purchases on the same delivery before calling Amazon.
        self.env.cr.execute(
            "SELECT id FROM stock_picking WHERE id = %s FOR UPDATE",
            [self.picking_id.id],
        )
        self.picking_id.invalidate_recordset(["amazon_label_purchased"])
        if self.picking_id.amazon_label_purchased:
            raise UserError(_("A label has already been purchased for this delivery."))
        if self.quoted_request != self._request_snapshot():
            raise UserError(_("Package details changed. Fetch shipping rates again."))
        channel = self.sale_channel_id
        res = channel._amazon_purchase_label(
            self.picking_id,
            rate.service_id,
            rate.service_offer_id,
            self.weight,
            self._dimensions(),
        )
        contents = res.get("label_contents")
        if not contents:
            raise UserError(_("Amazon returned no shipping label."))
        try:
            document = gzip.decompress(base64.b64decode(contents, validate=True))
        except (binascii.Error, ValueError, OSError, EOFError) as exc:
            raise UserError(_("Amazon returned an invalid label.")) from exc
        checksum = base64.b64encode(
            hashlib.md5(document, usedforsecurity=False).digest()
        ).decode()
        if res.get("label_checksum") != checksum:
            raise UserError(_("Amazon shipping label checksum does not match."))
        file_type = res.get("label_file_type")
        if file_type not in {"application/pdf", "image/png", "application/zpl"}:
            raise UserError(
                _("Unsupported Amazon shipping label format: %s") % file_type
            )
        extension = {
            "application/pdf": "pdf",
            "image/png": "png",
            "application/zpl": "zpl",
        }[file_type]

        currency = self.env["res.currency"].search(
            [("name", "=", (res.get("currency") or "USD"))], limit=1
        )
        attachment = self.env["ir.attachment"].create(
            {
                "name": f"amazon-label-{self.picking_id.name}.{extension}",
                "type": "binary",
                "datas": base64.b64encode(document),
                "mimetype": file_type,
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
