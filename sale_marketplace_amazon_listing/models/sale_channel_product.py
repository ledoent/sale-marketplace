# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SaleChannelProduct(models.Model):
    _inherit = "sale.channel.product"

    asin = fields.Char("ASIN", index=True)

    @api.model
    def _amazon_upsert(self, channel, product, sku, asin=None):
        """Create or update the channel binding for an Amazon SKU."""
        binding = self.search(
            [("sale_channel_id", "=", channel.id), ("external_id", "=", sku)],
            limit=1,
        )
        if binding:
            vals = {}
            if asin and binding.asin != asin:
                vals["asin"] = asin
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
                "asin": asin,
            }
        )
