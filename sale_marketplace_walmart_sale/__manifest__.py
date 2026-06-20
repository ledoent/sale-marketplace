# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Sale Marketplace Walmart Sale",
    "summary": "Import Walmart Marketplace orders into Odoo sale orders",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-marketplace",
    "license": "AGPL-3",
    "depends": [
        "sale_marketplace_walmart",
        "sale_marketplace_import",
        "sale_stock",
        "account",
        "queue_job",
    ],
    "data": [
        "data/ir_cron.xml",
        "views/sale_channel_views.xml",
        "views/sale_order_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
