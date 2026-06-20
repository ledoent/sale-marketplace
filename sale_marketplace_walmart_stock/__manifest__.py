# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Sale Marketplace Walmart Stock",
    "summary": "Push carrier tracking to Walmart via the Orders shipping API",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-marketplace",
    "license": "AGPL-3",
    "depends": [
        "sale_marketplace_walmart_sale",
        "stock_delivery",
        "queue_job",
    ],
    "data": [
        "views/stock_picking_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
