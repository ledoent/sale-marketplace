# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import api, fields, models


class SaleChannelDashboard(models.TransientModel):
    _name = "sale.channel.dashboard"
    _description = "Amazon Marketplace Dashboard"

    sale_channel_id = fields.Many2one(
        "sale.channel",
        string="Channel",
        domain=[("channel_type", "=", "amazon")],
        help="Leave empty to aggregate all Amazon channels.",
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    orders_total = fields.Integer(compute="_compute_kpis")
    orders_unshipped = fields.Integer(compute="_compute_kpis")
    listings_total = fields.Integer(compute="_compute_kpis")
    listings_buybox_us = fields.Integer(compute="_compute_kpis")
    buybox_win_rate = fields.Float(compute="_compute_kpis")
    price_changes_7d = fields.Integer(compute="_compute_kpis")
    offers_7d = fields.Integer(compute="_compute_kpis")
    avg_margin = fields.Float(compute="_compute_kpis")
    listings_below_margin = fields.Integer(compute="_compute_kpis")
    fba_skus = fields.Integer(compute="_compute_kpis")
    fba_drift_skus = fields.Integer(compute="_compute_kpis")
    fba_total_drift = fields.Integer(compute="_compute_kpis")
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
    last_fba_sync = fields.Datetime(compute="_compute_kpis")
    last_settlement_sync = fields.Datetime(compute="_compute_kpis")
    last_return_sync = fields.Datetime(compute="_compute_kpis")
    health_status = fields.Selection(
        [("ok", "OK"), ("attention", "Attention")], compute="_compute_kpis"
    )

    def _backends(self):
        self.ensure_one()
        if self.sale_channel_id:
            return self.sale_channel_id
        return self.env["sale.channel"].search([("channel_type", "=", "amazon")])

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
            winners = listings.filtered("buy_box_winner")
            dash.listings_buybox_us = len(winners)
            with_bb = listings.filtered(lambda binding: binding.buy_box_price)
            dash.buybox_win_rate = len(winners) / len(with_bb) if with_bb else 0.0
            priced = listings.filtered(lambda binding: binding.fee_basis_price)
            margins = priced.mapped("est_margin_pct")
            dash.avg_margin = sum(margins) / len(margins) if margins else 0.0
            dash.listings_below_margin = len(listings.filtered("below_target_margin"))
            dash.price_changes_7d = self.env[
                "sale.channel.product.price.history"
            ].search_count(
                [
                    ("sale_channel_product_id.sale_channel_id", "in", cids),
                    ("date", ">=", cutoff),
                ]
            )
            dash.offers_7d = self.env[
                "sale.channel.product.offer.snapshot"
            ].search_count(
                [
                    ("sale_channel_product_id.sale_channel_id", "in", cids),
                    ("date", ">=", cutoff),
                ]
            )

            fba = self.env["sale.channel.fba.inventory"].search(
                [("sale_channel_id", "in", cids)]
            )
            dash.fba_skus = len(fba)
            drift = fba.filtered(lambda record: record.drift)
            dash.fba_drift_skus = len(drift)
            dash.fba_total_drift = int(sum(abs(record.drift) for record in drift))

            group = self.env["sale.channel.settlement.group"]
            dash.settlement_groups = group.search_count(
                [("sale_channel_id", "in", cids)]
            )
            recon = self.env["sale.channel.settlement.reconciliation"]
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

            returns = self.env["sale.channel.return"]
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
            dash.last_order_sync = dash._latest(channels, "amazon_last_import_date")
            dash.last_price_sync = dash._latest(channels, "last_price_sync_date")
            dash.last_fba_sync = dash._latest(channels, "last_fba_sync_date")
            dash.last_settlement_sync = dash._latest(
                channels, "last_settlement_sync_date"
            )
            dash.last_return_sync = dash._latest(channels, "last_return_sync_date")
            dash.health_status = (
                "attention"
                if (
                    dash.failed_jobs
                    or dash.recon_variance
                    or dash.fba_drift_skus
                    or dash.listings_below_margin
                )
                else "ok"
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
            "sale.channel.settlement.reconciliation",
            self._channel_domain() + [("state", "=", "variance")],
        )

    def action_open_fba_drift(self):
        return self._action(
            "FBA Drift",
            "sale.channel.fba.inventory",
            self._channel_domain() + [("drift", "!=", 0)],
        )

    def action_open_returns_open(self):
        return self._action(
            "Open Returns",
            "sale.channel.return",
            self._channel_domain() + [("state", "in", ("new", "picking_created"))],
        )

    def action_open_failed_jobs(self):
        # queue.job is server-wide, not channel-scoped
        return self._action("Failed Jobs", "queue.job", [("state", "=", "failed")])
