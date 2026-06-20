# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SaleChannelProduct(models.Model):
    _inherit = "sale.channel.product"

    wpid = fields.Char("Walmart Product ID", index=True)
    walmart_publish = fields.Boolean(
        "Publish to Walmart",
        default=True,
        help="Include this binding when exporting an item feed to Walmart.",
    )

    @api.model
    def _walmart_upsert(self, channel, product, sku, wpid=None):
        """Create or update the channel binding for a Walmart SKU."""
        binding = self.search(
            [("sale_channel_id", "=", channel.id), ("external_id", "=", sku)],
            limit=1,
        )
        if binding:
            vals = {}
            if wpid and binding.wpid != wpid:
                vals["wpid"] = wpid
            if binding.product_id.id != product.id:
                vals["product_id"] = product.id
            if vals:
                binding.write(vals)
            return binding
        return self.create(
            {
                "sale_channel_id": channel.id,
                "product_id": product.id,
                "external_id": sku,
                "wpid": wpid,
            }
        )
