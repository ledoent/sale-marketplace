# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Sale Marketplace Amazon Fees",
    "summary": "Estimate Amazon selling fees and fee-aware margin per listing",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-marketplace",
    "license": "AGPL-3",
    "depends": [
        "sale_marketplace_amazon_pricing",
        "queue_job",
    ],
    "external_dependencies": {
        "python": ["python-amazon-sp-api"],
    },
    "data": [
        "data/ir_cron.xml",
        "views/sale_channel_product_views.xml",
        "views/sale_channel_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
