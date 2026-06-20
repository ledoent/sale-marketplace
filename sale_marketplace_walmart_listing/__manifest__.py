# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Sale Marketplace Walmart Listing",
    "summary": "Import Walmart items into channel product (SKU) bindings",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-marketplace",
    "license": "AGPL-3",
    "depends": [
        "sale_marketplace_walmart",
        "queue_job",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/sale_channel_walmart_feed_views.xml",
        "views/sale_channel_product_views.xml",
        "views/sale_channel_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
