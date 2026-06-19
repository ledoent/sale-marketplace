# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelProduct(models.Model):
    """Bind a product to a sale channel via the channel's external identifier.

    This is the product-side counterpart of ``sale.channel.partner``: it maps an
    external listing identifier (an Amazon seller SKU, an eBay listing id, ...) to
    an Odoo ``product.product`` for a given channel. Marketplace modules extend it
    with channel-specific data (ASIN, fee fields, pushed quantities, ...).
    """

    _name = "sale.channel.product"
    _description = "Sale Channel Product"
    _rec_name = "external_id"
    _sql_constraints = [
        (
            "product_channel_uniq",
            "unique(product_id, sale_channel_id)",
            "product-channel pairs for sale channel products are unique",
        ),
        (
            "external_id_channel_uniq",
            "unique(external_id, sale_channel_id)",
            "external_id-channel pairs for sale channel products are unique",
        ),
    ]

    sale_channel_id = fields.Many2one(
        "sale.channel", "Sale Channel", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one(
        "product.product", "Product", required=True, ondelete="cascade", index=True
    )
    external_id = fields.Char(
        "External ID",
        required=True,
        index=True,
        help="The product identifier on the external sale channel (e.g. SKU).",
    )
    active = fields.Boolean(default=True)
