# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Sale Marketplace Walmart Dashboard",
    "summary": "KPI dashboard across the Walmart marketplace suite",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-marketplace",
    "license": "AGPL-3",
    "depends": [
        "sale_marketplace_walmart_sale",
        "sale_marketplace_walmart_pricing",
        "sale_marketplace_walmart_inventory",
        "sale_marketplace_walmart_payment",
        "sale_marketplace_walmart_return",
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
