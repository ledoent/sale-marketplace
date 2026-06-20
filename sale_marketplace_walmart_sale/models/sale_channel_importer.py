# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class SaleChannelImporter(models.TransientModel):
    _inherit = "sale.channel.importer"

    def _get_product(self, line_data, company):
        """Resolve Walmart line products through the channel SKU binding first.

        For a Walmart channel the line ``product_code`` is the seller SKU; map it
        via ``sale.channel.product`` (external_id) before falling back to the
        generic ``default_code`` lookup.
        """
        channel = self.payload_id.sale_channel_id
        if channel.channel_type == "walmart":
            binding = self.env["sale.channel.product"].search(
                [
                    ("sale_channel_id", "=", channel.id),
                    ("external_id", "=", line_data["product_code"]),
                ],
                limit=1,
            )
            if binding:
                return binding.product_id
        return super()._get_product(line_data, company)

    def _prepare_sale_vals(self, data):
        vals = super()._prepare_sale_vals(data)
        channel = self.payload_id.sale_channel_id
        if channel.channel_type != "walmart":
            return vals
        if channel.warehouse_id:
            vals["warehouse_id"] = channel.warehouse_id.id
        # Apply the facilitator fiscal position so Odoo's tax compute maps the
        # product's customer taxes away (Walmart already collects/remits the tax).
        if channel.walmart_fiscal_position_id:
            vals["fiscal_position_id"] = channel.walmart_fiscal_position_id.id
        vals["walmart_collected_tax"] = self.payload_id.walmart_collected_tax
        return vals
