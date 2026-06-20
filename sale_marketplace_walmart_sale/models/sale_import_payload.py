# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleImportPayload(models.Model):
    _inherit = "sale.import.payload"

    # Carries the marketplace-collected (facilitator) tax from the connector to
    # the importer, which stamps it on the created sale order. Kept off the
    # sale_import_base SaleOrder schema (which is validated and drops unknown
    # keys), so it travels as a payload field instead.
    walmart_collected_tax = fields.Float(readonly=True)
