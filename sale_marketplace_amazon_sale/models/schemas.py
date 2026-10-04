# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.addons.sale_import_base.models.schemas import SaleOrderLine


class AmazonSaleOrderLine(SaleOrderLine, extends=True):
    amazon_order_item_id: str | None = None
