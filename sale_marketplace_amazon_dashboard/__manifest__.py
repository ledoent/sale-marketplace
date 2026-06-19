# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Sale Marketplace Amazon Dashboard",
    "summary": "KPI dashboard across the Amazon marketplace suite",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-marketplace",
    "license": "AGPL-3",
    "depends": [
        "sale_marketplace_amazon_sale",
        "sale_marketplace_amazon_pricing",
        "sale_marketplace_amazon_repricing",
        "sale_marketplace_amazon_fees",
        "sale_marketplace_amazon_fba",
        "sale_marketplace_amazon_payment",
        "sale_marketplace_amazon_return",
        "queue_job",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_channel_dashboard_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
