# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import api, fields, models


class SaleChannelWalmartDashboard(models.TransientModel):
    _name = "sale.channel.walmart.dashboard"
    _description = "Walmart Marketplace Dashboard"

    sale_channel_id = fields.Many2one(
        "sale.channel",
        string="Channel",
        domain=[("channel_type", "=", "walmart")],
        help="Leave empty to aggregate all Walmart channels.",
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    orders_total = fields.Integer(compute="_compute_kpis")
    orders_unshipped = fields.Integer(compute="_compute_kpis")
    listings_total = fields.Integer(compute="_compute_kpis")
    listings_inventory_synced = fields.Integer(compute="_compute_kpis")
    price_changes_7d = fields.Integer(compute="_compute_kpis")
    settlement_groups = fields.Integer(compute="_compute_kpis")
    recon_matched = fields.Integer(compute="_compute_kpis")
    recon_variance = fields.Integer(compute="_compute_kpis")
    recon_no_invoice = fields.Integer(compute="_compute_kpis")
    recon_variance_amount = fields.Float(compute="_compute_kpis")
    returns_open = fields.Integer(compute="_compute_kpis")
    returns_credited = fields.Integer(compute="_compute_kpis")
    failed_jobs = fields.Integer(compute="_compute_kpis")
    last_order_sync = fields.Datetime(compute="_compute_kpis")
    last_price_sync = fields.Datetime(compute="_compute_kpis")
    last_inventory_sync = fields.Datetime(compute="_compute_kpis")
    last_settlement_sync = fields.Datetime(compute="_compute_kpis")
    last_return_sync = fields.Datetime(compute="_compute_kpis")
    health_status = fields.Selection(
        [("ok", "OK"), ("attention", "Attention")], compute="_compute_kpis"
    )

    def _backends(self):
        self.ensure_one()
        if self.sale_channel_id:
            return self.sale_channel_id
        return self.env["sale.channel"].search([("channel_type", "=", "walmart")])

    @staticmethod
    def _latest(channels, field):
        values = [channel[field] for channel in channels if channel[field]]
        return max(values) if values else False

    @api.depends("sale_channel_id")
    def _compute_kpis(self):
        for dash in self:
            channels = dash._backends()
            cids = channels.ids
            cutoff = fields.Datetime.now() - timedelta(days=7)

            sale_order = self.env["sale.order"]
            dash.orders_total = sale_order.search_count(
                [("sale_channel_id", "in", cids)]
            )
            dash.orders_unshipped = sale_order.search_count(
                [("sale_channel_id", "in", cids), ("state", "=", "sale")]
            )

            listings = self.env["sale.channel.product"].search(
                [("sale_channel_id", "in", cids)]
            )
            dash.listings_total = len(listings)
            dash.listings_inventory_synced = len(
                listings.filtered("inventory_sync_enabled")
            )
            dash.price_changes_7d = self.env[
                "sale.channel.product.walmart.price.history"
            ].search_count(
                [
                    ("sale_channel_product_id.sale_channel_id", "in", cids),
                    ("date", ">=", cutoff),
                ]
            )

            group = self.env["sale.channel.walmart.settlement.group"]
            dash.settlement_groups = group.search_count(
                [("sale_channel_id", "in", cids)]
            )
            recon = self.env["sale.channel.walmart.settlement.reconciliation"]
            dash.recon_matched = recon.search_count(
                [("sale_channel_id", "in", cids), ("state", "=", "matched")]
            )
            variance_recs = recon.search(
                [("sale_channel_id", "in", cids), ("state", "=", "variance")]
            )
            dash.recon_variance = len(variance_recs)
            dash.recon_variance_amount = sum(variance_recs.mapped("variance"))
            dash.recon_no_invoice = recon.search_count(
                [("sale_channel_id", "in", cids), ("state", "=", "no_invoice")]
            )

            returns = self.env["sale.channel.walmart.return"]
            dash.returns_open = returns.search_count(
                [
                    ("sale_channel_id", "in", cids),
                    ("state", "in", ("new", "picking_created")),
                ]
            )
            dash.returns_credited = returns.search_count(
                [
                    ("sale_channel_id", "in", cids),
                    ("state", "in", ("credited", "done")),
                ]
            )

            dash.failed_jobs = self.env["queue.job"].search_count(
                [("state", "=", "failed")]
            )
            dash.last_order_sync = dash._latest(channels, "walmart_last_import_date")
            dash.last_price_sync = dash._latest(
                channels, "walmart_last_price_sync_date"
            )
            dash.last_inventory_sync = dash._latest(
                channels, "last_inventory_sync_date"
            )
            dash.last_settlement_sync = dash._latest(
                channels, "walmart_last_settlement_sync_date"
            )
            dash.last_return_sync = dash._latest(
                channels, "walmart_last_return_sync_date"
            )
            dash.health_status = (
                "attention" if (dash.failed_jobs or dash.recon_variance) else "ok"
            )

    # ------------------------------------------------------------------
    # Drill-downs
    # ------------------------------------------------------------------
    def _action(self, name, model, domain):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": "list,form",
            "domain": domain,
        }

    def _channel_domain(self):
        return [("sale_channel_id", "in", self._backends().ids)]

    def action_open_recon_variance(self):
        return self._action(
            "Reconciliation Variance",
            "sale.channel.walmart.settlement.reconciliation",
            self._channel_domain() + [("state", "=", "variance")],
        )

    def action_open_returns_open(self):
        return self._action(
            "Open Returns",
            "sale.channel.walmart.return",
            self._channel_domain() + [("state", "in", ("new", "picking_created"))],
        )

    def action_open_failed_jobs(self):
        # queue.job is server-wide, not channel-scoped
        return self._action("Failed Jobs", "queue.job", [("state", "=", "failed")])
